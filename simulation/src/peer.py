import analyze as an
import util
from util import SortedIterSet
import simpy
import itertools as it
from copy import deepcopy
from collections import namedtuple, OrderedDict, deque
import random
import operator as op
import numpy as np


query_group_id_iter = it.count()


class PeerBehavior:
    def __init__(self, peer):
        self.peer = peer

    def on_query_self(self, querying_peer_id, queried_id, in_event_id):
        """React to a query for own ID."""
        rep = self.peer.expected_min_reputation(querying_peer_id)
        enough_rep = (self.peer.settings['reputation_buffer_factor']
                      * self.peer.settings['no_penalty_reputation'])
        delay = self.decide_delay(querying_peer_id)
        if querying_peer_id != self.peer.peer_id and rep >= enough_rep:
            self.peer.expect_penalty(
                querying_peer_id, self.peer.settings['timeout_query_penalty'],
                delay + self.peer.settings['expected_penalty_timeout_buffer'],
                in_event_id)
            return
        self.peer.send_response(querying_peer_id, SortedIterSet((queried_id,)),
                                self.peer.info(), in_event_id, delay=delay)

    def on_query_sync(self, querying_peer_id, queried_id, sync_peer_info,
                      in_event_id):
        """React to a query for the ID of a sync peer."""
        rep = self.peer.expected_min_reputation(querying_peer_id)
        enough_rep = (self.peer.settings['reputation_buffer_factor']
                      * self.peer.settings['no_penalty_reputation'])
        delay = self.decide_delay(querying_peer_id)
        if querying_peer_id != self.peer.peer_id and rep >= enough_rep:
            self.peer.expect_penalty(
                querying_peer_id, self.peer.settings['timeout_query_penalty'],
                delay + self.peer.settings['expected_penalty_timeout_buffer'],
                in_event_id)
            return
        self.peer.send_response(querying_peer_id, SortedIterSet((queried_id,)),
                                sync_peer_info, in_event_id, delay=delay)

    def on_query(self, querying_peer_id, queried_id, in_event_id,
                 query_further=False, query_sync=False):
        """
        React to a query.

        This method implements the "good" default behavior. A list of peers is
        created that will be queried and sorted based on how close they are to
        the queried ID. A PendingQuery is created with these peers and used to
        send a query.

        By default, the peers that will be queried are only ones whose prefix
        has a larger overlap with the queried ID than this peer, i.e. who are
        closer to the target ID. However, if query_all is True, all query
        peers, will be queried.

        If query_sync is True, sync peers will also be queried.
        """
        rep = self.peer.expected_min_reputation(querying_peer_id)
        enough_rep = (self.peer.settings['reputation_buffer_factor']
                      * self.peer.settings['no_penalty_reputation'])
        delay = self.decide_delay(querying_peer_id)
        if querying_peer_id != self.peer.peer_id and rep >= enough_rep:
            self.peer.expect_penalty(
                querying_peer_id, self.peer.settings['timeout_query_penalty'],
                delay + self.peer.settings['expected_penalty_timeout_buffer'],
                in_event_id)
            return
        if query_further or query_sync:
            peers_to_query_info = []
            if query_further:
                peers_to_query_info = list(pi for _, pi
                                           in self.peer.known_query_peers())
            if query_sync:
                peers_to_query_info += [i for i
                                        in self.peer.sync_peers.values()
                                        if i.peer_id != self.peer.peer_id]
            self.sort_peers_to_query(peers_to_query_info, queried_id)
            peers_to_query = [pi.peer_id for pi in peers_to_query_info]
        else:
            peers_to_query = self.select_peers_to_query(queried_id)
        if len(peers_to_query) == 0:
            if querying_peer_id == self.peer.peer_id:
                self.peer.finalize_query('impossible', in_event_id)
            else:
                self.peer.expect_penalty(
                    querying_peer_id,
                    self.peer.settings['failed_query_penalty'], delay
                    + self.peer.settings['expected_penalty_timeout_buffer'],
                    in_event_id)
                self.peer.send_response(
                    querying_peer_id, SortedIterSet((queried_id,)), None,
                    in_event_id, delay=delay)
            return
        pending_query = PendingQuery(self.peer.env.now, querying_peer_id,
                                     queried_id, peers_to_query)
        self.peer.add_pending_query(queried_id, pending_query)
        self.peer.send_query(queried_id, pending_query, in_event_id)
        # TODO Send queries to multiple peers at once.

    def on_response_success(self, pending_query, responding_peer_id,
                            queried_peer_info, in_event_id):
        """React to a successful response arriving."""
        if self.peer.peer_id in pending_query.querying_peers:
            self.peer.finalize_query('success', in_event_id)
            del pending_query.querying_peers[self.peer.peer_id]
        total_time = self.peer.env.now - pending_query.start_time
        # TODO Update the ID/address mapping, even if we're just passing the
        # query result through to another peer.
        for querying_peer_id, queried_ids in (pending_query.querying_peers
                                              .items()):
            delay = max(0, self.decide_delay(querying_peer_id) - total_time)
            self.peer.send_response(querying_peer_id, queried_ids,
                                    queried_peer_info, in_event_id,
                                    delay=delay)
        self.do_rep_success(responding_peer_id, in_event_id)

    def on_response_failure(self, pending_query, responding_peer_id,
                            in_event_id):
        """
        React to an ultimately failed response arriving.

        A response has failed ultimately if the query cannot be retried because
        there are no further peers to query.
        """
        if self.peer.peer_id in pending_query.querying_peers:
            self.peer.finalize_query('failure', in_event_id)
            del pending_query.querying_peers[self.peer.peer_id]
        total_time = self.peer.env.now - pending_query.start_time
        for querying_peer_id, queried_ids in (pending_query.querying_peers
                                              .items()):
            delay = max(0, self.decide_delay(querying_peer_id) - total_time)
            self.peer.send_response(querying_peer_id, queried_ids, None,
                                    in_event_id, delay=delay)
        self.do_rep_failure(responding_peer_id, in_event_id)

    def on_response_retry(self, pending_query, responding_peer_id, queried_id,
                          in_event_id):
        """React to a failed response that can be retried."""
        self.peer.send_query(queried_id, pending_query, in_event_id)
        self.do_rep_failure(responding_peer_id, in_event_id)

    def on_timeout_failure(self, pending_query, recipient_id, in_event_id):
        """
        React to a query timing out and failing ultimately.

        A query has failed ultimately if it can't be retried because there are
        no further peers to query.
        """
        if self.peer.peer_id in pending_query.querying_peers:
            self.peer.finalize_query('timeout', in_event_id)
            del pending_query.querying_peers[self.peer.peer_id]
        total_time = self.peer.env.now - pending_query.start_time
        for querying_peer_id, queried_ids in (pending_query.querying_peers
                                              .items()):
            delay = max(0, self.decide_delay(querying_peer_id) - total_time)
            self.peer.send_response(querying_peer_id, queried_ids, None,
                                    in_event_id, delay=delay)
        self.do_rep_timeout(recipient_id, in_event_id)

    def on_timeout_retry(self, pending_query, recipient_id, queried_id,
                         in_event_id):
        """React to a query timing out that can be retried."""
        self.peer.send_query(queried_id, pending_query, in_event_id)
        self.do_rep_timeout(recipient_id, in_event_id)

    def on_response_late_success(self, responding_peer_id):
        """
        React to a successful response arriving late.

        A response is late if the query has already been successfully answered
        by another peer.
        """
        # TODO Using None as in_event_id because we're not storing the ID of
        # the event leading to this.
        self.do_rep_success(responding_peer_id, None)

    def on_response_late_failure(self, responding_peer_id):
        """
        React to a failed response arriving late.

        A response is late if the query has already been successfully answered
        by another peer.
        """
        # Don't apply a penalty here, as one has already been applied for the
        # timeout.
        pass

    def do_rep_success(self, peer_id, in_event_id):
        """Do the reputation update after a successful query."""
        self.peer.send_reputation_update(
            peer_id, self.peer.settings['successful_query_reward'],
            in_event_id)

    def do_rep_failure(self, peer_id, in_event_id):
        """Do the reputation update after a failed query."""
        self.peer.send_reputation_update(
            peer_id, self.peer.settings['failed_query_penalty'], in_event_id)

    def do_rep_timeout(self, peer_id, in_event_id):
        """Do the reputation update after a timed out query."""
        self.peer.send_reputation_update(
            peer_id, self.peer.settings['timeout_query_penalty'], in_event_id)

    def decide_delay(self, querying_peer_id):
        """Decide what penalty delay to impose."""
        max_rep = self.peer.max_peer_reputation(querying_peer_id,
                                                querying_peer_id)
        npr = self.peer.settings['no_penalty_reputation']
        return min(max(npr - max_rep, 0), npr)

    def expect_delay(self, peer_to_query_id):
        """Predict the penalty delay that will be imposed."""
        max_rep = self.peer.max_peer_reputation(self.peer.peer_id,
                                                peer_to_query_id)
        npr = self.peer.settings['no_penalty_reputation']
        return min(max(npr - max_rep, 0), npr)

    def select_peers_to_query(self, queried_id):
        """
        List peers to send a query to.

        Creates a list containing all peers that should be queried for the
        given ID. These are all known peers who are closer to that ID, i.e.
        whose bit_overlap() is larger than for this peer.
        """
        own_overlap = util.bit_overlap(self.peer.prefix, queried_id)
        peers_to_query_info = []
        for _, query_peer_info in self.peer.known_query_peers():
            # TODO Range queries for performance.
            if (util.bit_overlap(query_peer_info.prefix, queried_id)
                    > own_overlap):
                peers_to_query_info.append(query_peer_info)
        self.sort_peers_to_query(peers_to_query_info, queried_id)
        return [pi.peer_id for pi in peers_to_query_info]

    def sort_peers_to_query(self, peer_infos, queried_id):
        """
        Sort a list of PeerInfos according to the peer selection strategy.

        Also removes duplicates.

        The order of the list depends on the query_peer_selection value in the
            settings. Possible values are:
            * 'overlap': Create a list of all query peers whose prefix has a
                higher overlap with the queried ID than one's own. Sort this
                list by the length of that overlap, greatest first. No tie
                breaker.
            * 'overlap_high_rep_last': As 'overlap', but all peers with enough
                reputation (i.e. whose minimum reputation in all shared query
                groups is greater than or equal 'no_penalty_reputation' times
                'reputation_buffer_factor' are taken from the front and added
                to the back.
            * 'shuffled': Like 'overlap', except the list is shuffled instead
                of sorted.
            * 'overlap_rep_sorted': As 'overlap' but within groups of equal
                overlap, peers are sorted by reputation in ascending order.
            * 'rep_sorted': Peers are sorted by reputation in ascending_order.
        """
        if (self.peer.settings['query_peer_selection']
                not in ('overlap', 'overlap_high_rep_last', 'shuffled',
                        'overlap_rep_sorted', 'rep_sorted')):
            raise Exception(
                'Invalid query peer selection strategy {}.'
                .format(self.peer.settings['query_peer_selection']))
        util.remove_duplicates(peer_infos, key=op.attrgetter('peer_id'))
        if (self.peer.settings['query_peer_selection']
                in ('overlap', 'overlap_high_rep_last')):
            peer_infos.sort(key=lambda pi: util.bit_overlap(pi.prefix,
                                                            queried_id),
                            reverse=True)
        elif self.peer.settings['query_peer_selection'] == 'shuffled':
            random.shuffle(peer_infos)
        elif (self.peer.settings['query_peer_selection']
                == 'overlap_rep_sorted'):
            def key(peer_info):
                overlap = util.bit_overlap(peer_info.prefix, queried_id)
                min_rep = self.peer.min_peer_reputation(peer_info.peer_id)
                return (overlap, -min_rep)
            peer_infos.sort(key=key, reverse=True)
        elif self.peer.settings['query_peer_selection'] == 'rep_sorted':
            def key(peer_info):
                return self.peer.min_peer_reputation(peer_info.peer_id)
            peer_infos.sort(key=key)
        if (self.peer.settings['query_peer_selection']
                == 'overlap_high_rep_last'):
            enough_rep = (self.peer.settings['reputation_buffer_factor']
                          * self.peer.settings['no_penalty_reputation'])
            swap_back_idxs = []
            for i, peer_info in enumerate(peer_infos):
                min_rep = self.peer.min_peer_reputation(peer_info.peer_id)
                if min_rep >= enough_rep:
                    swap_back_idxs.append(i - len(swap_back_idxs))
            for idx in swap_back_idxs:
                peer_info = peer_infos.pop(idx)
                peer_infos.append(peer_info)

    def query_group_performs(self, query_group_id):
        """
        Return whether a query group offers good performance.

        Performance is measured by how much reputation the peer can gain in the
        group. The peer's reputation history in the group is examined. If the
        last record is above a threshold relative to the reputation at which no
        penalty is imposed, the group is considered to perform well. It is also
        thus considered if there is not enough recent reputation data (to give
        it some time). Otherwise, a linear regression is applied to the recent
        reputation data. The group is then considered to perform well if the
        slope is above a threshold (i.e. the peer is able to gain reputation
        over time).
        """
        history = self.peer.query_group_history.get(query_group_id)
        if history is None:
            # No history has been recorded yet. This can happen if the history
            # update interval is long. Assume it performs for now.
            assert query_group_id in self.peer.query_groups
            return True
        if len(history) < self.peer.settings['query_group_min_history']:
            # Membership is too young, assume it performs for the moment.
            return True
        min_rep = (self.peer.settings['no_penalty_reputation']
                   * self.peer.settings['performance_no_penalty_fraction'])
        if history[-1] >= min_rep:
            return True
        interval = self.peer.settings['query_group_history_interval']
        recent_reps = []
        for rep in it.islice(
                reversed(history),
                self.peer.settings['performance_num_history_entries']):
            recent_reps.insert(0, rep)
        slope, _ = np.polyfit(range(0, len(recent_reps) * interval, interval),
                              recent_reps, 1)
        return slope >= self.peer.settings['performance_min_slope']

    def reevaluate_query_groups(self, in_event_id):
        """
        Evaluate performance of query groups and make adjustments.

        Checks the performance of query groups and tries to leave those with
        bad performance. Only does so if this doesn't reduce subprefix coverage
        below the minimum configured level for any subprefix (i.e. minimum
        number of query peers per subprefix). But tries to find a replacement
        in order to leave groups with low performance via
        Peer.find_query_peers_for().
        """
        # TODO Also check that subprefixes are still covered. Peers covering
        # them may have left the group.
        group_coverage = self.peer.query_group_subprefix_coverage()
        query_group_ids = list(group_coverage.keys())
        # TODO Start with the worst performing query group, get rid of it
        # first.
        for query_group_id in query_group_ids:
            if self.query_group_performs(query_group_id):
                continue
            can_be_removed = True
            coverage = group_coverage[query_group_id]
            for subprefix in (sp for sp, ps in coverage.items() if ps):
                covering_peer_ids = SortedIterSet(it.chain(*(
                    pc[subprefix] for gid, pc in group_coverage.items()
                    if gid != query_group_id)))
                num_missing_peers\
                    = (self.peer.settings['min_desired_query_peers']
                       - len(covering_peer_ids))
                if num_missing_peers > 0:
                    usefulness\
                        = self.peer.estimated_usefulness_in(query_group_id)
                    replacements_found = self.peer.find_query_peers_for(
                        subprefix, covering_peer_ids, num_missing_peers,
                        usefulness, in_event_id)
                    if replacements_found:
                        # Refresh group_coverage, since a group was added.
                        group_coverage\
                            = self.peer.query_group_subprefix_coverage()
                    else:
                        can_be_removed = False
            if can_be_removed:
                del group_coverage[query_group_id]
                self.peer.leave_query_group(query_group_id, in_event_id)


class Peer:
    def __init__(self, env, logger, network, peer_id, all_query_groups,
                 all_prefixes, settings, start_processes=True):
        self.env = env
        self.logger = logger
        self.network = network
        self.peer_id = peer_id
        self.all_query_groups = all_query_groups
        self.all_prefixes = all_prefixes
        self.settings = settings
        self.prefix = self.peer_id[:self.settings['prefix_length']]
        self.query_groups = OrderedDict()
        self.sync_peers = OrderedDict()
        self.pending_queries = OrderedDict()
        self.completed_queries = OrderedDict()
        self.address = self.network.register(self)
        self.behavior = PeerBehavior(self)
        self.query_group_history = OrderedDict()
        self.expected_penalties = OrderedDict()

        # Add self-loop to the peer graph so that networkx considers the node
        # for this peer a component.
        self.logger.log(an.ConnectionAdd(self.env.now, self.peer_id,
                                         self.peer_id, None))
        if start_processes:
            util.do_repeatedly(self.env,
                               self.settings['query_group_history_interval'],
                               self.update_query_group_history)
            util.do_repeatedly(
                self.env, self.settings['query_group_reevaluation_interval'],
                self.reevaluate_query_groups)

    def __lt__(self, other):
        return self.peer_id < other.peer_id

    def info(self):
        return PeerInfo(self.peer_id, self.prefix, self.address)

    def lookup_address_local(self, peer_id):
        """
        Locally look up an address belonging to an ID.

        Only checks local information, no messages are sent on the network,
        even if there is no local information.
        Returns the address, or None if it is not known.
        """
        info = self.sync_peers.get(peer_id)
        if info is not None:
            return info.address
        for query_group in self.query_groups.values():
            peer_info = query_group.get(peer_id)
            if peer_info is None:
                continue
            return peer_info.address
        return None

    def peer_is_known(self, peer_id):
        """Return whether a peer is known and can be contacted."""
        # OPTI Do the check for query peers more efficiently (one set).
        return (peer_id in (p.peer_id for _, p in self.known_query_peers())
                or peer_id in self.sync_peers)

    def pending_query_has_known_query_peer(self, pending_query):
        """
        Return whether one of the possible recipients is a known query peer.

        Removes all peers from the front of the peers_to_query list that are
        not.
        """
        # TODO Should sync peers also be considered? Shouldn't normally send
        # queries to them.
        # OPTI Do the check for query peers more efficiently (one set).
        while (pending_query.peers_to_query
               and pending_query.peers_to_query[0]
               not in (p.peer_id for _, p in self.known_query_peers())):
            pending_query.peers_to_query.pop(0)
        return len(pending_query.peers_to_query) > 0

    def add_to_query_group(self, query_group, peer):
        """
        Add a peer to the query groups at all members.

        TODO Workaround while the group invite system isn't implemented. Makes
        use of the network to get a hold of actual peer references via their
        address.
        """
        for query_peer_info in query_group.infos():
            query_peer = self.network.peers[query_peer_info.address]
            assert query_peer.peer_id == query_peer_info.peer_id
            if query_peer == self:
                continue
            qg = query_peer.query_groups[query_group.query_group_id]
            qg[peer.peer_id] = QueryPeerInfo(
                peer.info(), self.settings['initial_reputation'])

    def join_group_with(self, peer_info):
        """
        Share a query group with another peer.

        First tries to join a query group that the other peer is already a
        member of (by checking all_query_groups). If not possible, tries to
        add the other peer to one of this peer's groups. Otherwise, creates a
        new group.

        If this peer already shares a group with the other, join or creates
        another.
        """
        # TODO Remove this hack. We need to add the new query group to the
        # other peer's set of query groups. But the only place storing the peer
        # references is the network, so we have to abuse its private peer map.
        # Remove this once query group invites are implemented.
        peer = self.network.peers[peer_info.address]
        assert peer.peer_id == peer_info.peer_id
        try:
            # TODO Instead of just adding self or others to groups, send join
            # requests or invites.
            # Attempt to join one of the peer's groups.
            # TODO Don't use the global information all_query_groups.
            for query_group in self.all_query_groups.values():
                # TODO Pick the most useful out of these groups, not just any.
                if (peer_info.peer_id in query_group
                        and len(query_group)
                        < self.settings['max_desired_group_size']
                        and self.peer_id not in query_group):
                    self.add_to_query_group(query_group, self)
                    query_group_copy = deepcopy(query_group)
                    query_group_copy[self.peer_id] = QueryPeerInfo(
                        self.info(), self.settings['initial_reputation'])
                    self.query_groups[query_group.query_group_id]\
                        = query_group_copy
                    self.all_query_groups[query_group.query_group_id]\
                        = deepcopy(query_group_copy)
                    self.logger.log(
                        an.QueryGroupAdd(self.env.now, self.peer_id,
                                         query_group.query_group_id, None))
                    return
            # Attempt to add the peer to one of my groups.
            for query_group in self.query_groups.values():
                # TODO Pick the most useful out of these groups, not just any.
                if (len(query_group) < self.settings['max_desired_group_size']
                        and peer_info.peer_id not in query_group):
                    self.add_to_query_group(query_group, peer)
                    query_group[peer_info.peer_id] = QueryPeerInfo(
                        peer_info, self.settings['initial_reputation'])
                    query_group_copy = deepcopy(query_group)
                    peer.query_groups[query_group.query_group_id]\
                        = query_group_copy
                    self.all_query_groups[query_group.query_group_id]\
                        = deepcopy(query_group_copy)
                    self.logger.log(
                        an.QueryGroupAdd(self.env.now, peer_info.peer_id,
                                         query_group.query_group_id, None))
                    return
            # Create a new query group.
            query_group = QueryGroup(next(query_group_id_iter),
                                     (self.info(), peer_info),
                                     self.settings['initial_reputation'])
            self.all_query_groups[query_group.query_group_id] = query_group
            self.query_groups[query_group.query_group_id]\
                = deepcopy(query_group)
            peer.query_groups[query_group.query_group_id]\
                = deepcopy(query_group)
            self.logger.log(an.QueryGroupAdd(self.env.now, self.peer_id,
                                             query_group.query_group_id, None))
            self.logger.log(an.QueryGroupAdd(self.env.now, peer_info.peer_id,
                                             query_group.query_group_id, None))
        finally:
            # Update the set of uncovered subprefixes for every member of the
            # query group. This may not actually change anything, but it's the
            # easiest way of maintaining the current data.
            for query_peer_info in query_group.infos():
                # TODO Remove this hack. See comment at the beginning.
                query_peer = self.network.peers[query_peer_info.address]
                assert query_peer.peer_id == query_peer_info.peer_id
                self.logger.log(
                    an.UncoveredSubprefixes(
                        self.env.now, query_peer.peer_id,
                        SortedIterSet(query_peer.uncovered_subprefixes()),
                        None))

    def start_missing_query_peer_search(self):
        self.find_missing_query_peers()
        util.do_repeatedly(self.env,
                           self.settings['uncovered_subprefix_interval'],
                           Peer.find_missing_query_peers, self)

    def find_missing_query_peers(self):
        """
        Find peers to cover subprefixes for which there are no known peers.

        It's not enough in this case to simply query for a prefix, because
        there may not be any known peer closer to it. Instead, peers who are
        further away are also queried by calling on_query() directly with
        query_further set to True.

        If query_sync_for_subprefixes is set in the settings, sync peers will
        be queried as well.
        """
        in_event_id = None
        for subprefix in (sp for sp, c in self.subprefix_coverage().items()
                          if c < self.settings['min_desired_query_peers']):
            if (self.settings['ignore_non_existent_subprefixes']
                    and not self.subprefix_exists(subprefix)):
                continue
            for queried_id in self.pending_queries.keys():
                if queried_id.startswith(subprefix):
                    # There is a pending query that will satisfy the subprefix
                    # when successful.
                    break
            else:
                if in_event_id is None:
                    in_event_id = self.logger.log(an.UncoveredSubprefixSearch(
                        self.env.now, self.peer_id, None))
                query_sync = self.settings['query_sync_for_subprefixes']
                self.behavior.on_query(
                    self.peer_id, subprefix, in_event_id, query_further=True,
                    query_sync=query_sync)

    def introduce(self, peer_info):
        """
        Introduce another peer to this peer.

        If the peer is already known, the address is updated.

        This peer will be able to directly contact the other peer without
        needing to look up the ID/address mapping.
        """
        if peer_info.peer_id == self.peer_id:
            return
        if peer_info.peer_id.startswith(self.prefix):
            self.sync_peers[peer_info.peer_id] = peer_info
            self.logger.log(an.ConnectionAdd(self.env.now, self.peer_id,
                                             peer_info.peer_id, None))
            return
        is_known = False
        for query_group in self.peer_query_groups(peer_info.peer_id):
            is_known = True
            query_group[peer_info.peer_id].address = peer_info.address
        if not is_known:
            for sp, count in self.subprefix_coverage().items():
                if (peer_info.prefix.startswith(sp)
                        and count < self.settings['min_desired_query_peers']):
                    self.join_group_with(peer_info)
                    self.logger.log(an.ConnectionAdd(self.env.now,
                                                     self.peer_id,
                                                     peer_info.peer_id, None))

    def subprefixes(self):
        """
        Return an ordered list of the subprefixes of this peer.

        See subprefixes().
        """
        return subprefixes(self.prefix)

    def subprefix_coverage(self):
        """
        Map each subprefix to the number of known peers serving it.

        The dictionary that is returned maps each of the possible
        len(self.prefix) subprefixes to the number of peers this peer knows who
        can serve it.
        """
        coverage = OrderedDict((sp, SortedIterSet())
                               for sp in self.subprefixes())
        for _, query_peer_info in self.known_query_peers():
            for sp in self.subprefixes():
                if query_peer_info.prefix.startswith(sp):
                    coverage[sp].add(query_peer_info.peer_id)
                    break
        return OrderedDict((sp, len(qps)) for (sp, qps) in coverage.items())

    def uncovered_subprefixes(self):
        """Return subprefixes for which no peer is known."""
        return (sp for sp, c in self.subprefix_coverage().items() if c == 0)

    def subprefix_exists(self, subprefix):
        for prefix in self.all_prefixes:
            if prefix.startswith(subprefix):
                return True
        return False

    def query_group_subprefix_coverage(self):
        """
        Map each query group to the subprefixes covered by peers in it.

        The dictionary that is returned maps each query group ID to a
        dictionary that maps each of the possible len(self.prefix) subprefixes
        to the set of IDs of the peers in the query group that serve that
        subprefix.
        """
        coverage = OrderedDict((sp, SortedIterSet())
                               for sp in self.subprefixes())
        query_group_coverage = OrderedDict((gid, deepcopy(coverage))
                                           for gid in self.query_groups.keys())
        for query_group_id, query_peer_info in self.known_query_peers():
            coverage = query_group_coverage[query_group_id]
            for sp in coverage.keys():
                if query_peer_info.prefix.startswith(sp):
                    coverage[sp].add(query_peer_info.peer_id)
                    break
        return query_group_coverage

    def reevaluate_query_groups(self):
        in_event_id = self.logger.log(an.QueryGroupReevaluation(
            self.env.now, self.peer_id, None))
        self.behavior.reevaluate_query_groups(in_event_id)

    def find_query_peers_for(self, subprefix, covering_peer_ids,
                             num_missing_peers, min_usefulness, in_event_id):
        """
        Find query groups with peers covering a subprefix.

        Accesses the shared all_query_groups to find one or multiple query
        groups this peer is not a member of that contains peers previously
        unknown that cover a certain subprefix. If it finds such groups, joins
        them.

        Returns whether enough such peers were found.

        :param subprefix: The subprefix that should be covered.
        :param covering_peer_ids: A set of peer IDs that will be considered
            already known by this peer. If a query group is being considered
            and contains one of these peers, the peer will not count to the
            number of new peers found.
        :param num_missing_peers: The number of peers that should be found
            covering the subprefix.
        :param min_usefulness: The usefulness a new group must at least have.
        """
        # TODO Don't use the shared all_query_groups.
        for query_group_id, query_group in self.all_query_groups.items():
            if query_group_id in self.query_groups:
                continue
            if len(query_group) >= self.settings['max_desired_group_size']:
                continue
            # TODO Sort all available groups by usefulness, pick the most
            # useful one.
            if self.estimated_usefulness_in(query_group_id) < min_usefulness:
                # New group would likely perform worse.
                continue
            num_covering_peers = sum(1 for qpi in query_group.infos()
                                     if qpi.prefix.startswith(subprefix)
                                     and qpi.peer_id not in covering_peer_ids)
            if num_covering_peers:
                # TODO Factor out.
                self.query_groups[query_group_id] = deepcopy(
                    self.all_query_groups[query_group_id])
                qpi = QueryPeerInfo(self.info(),
                                    self.settings['initial_reputation'])
                self.query_groups[query_group_id][self.peer_id] = qpi
                self.all_query_groups[query_group_id][self.peer_id]\
                    = deepcopy(qpi)
                self.add_to_query_group(self.query_groups[query_group_id],
                                        self)
                self.logger.log(an.QueryGroupAdd(self.env.now, self.peer_id,
                                                 query_group_id, in_event_id))
            num_missing_peers -= num_covering_peers
            if num_missing_peers <= 0:
                return True
        return False

    def leave_query_group(self, query_group_id, in_event_id):
        self.logger.log(an.QueryGroupRemove(self.env.now, self.peer_id,
                                            query_group_id, in_event_id))
        for qpi in self.query_groups[query_group_id].infos():
            if qpi.peer_id == self.peer_id:
                continue
            # TODO Remove this hack once query groups are handled via messages.
            query_peer = self.network.peers[qpi.address]
            assert query_peer.peer_id == qpi.peer_id
            del query_peer.query_groups[query_group_id][self.peer_id]
        del self.query_groups[query_group_id]
        self.query_group_history.pop(query_group_id, None)
        del self.all_query_groups[query_group_id][self.peer_id]

    def update_query_group_history(self):
        for query_group_id, query_group in self.query_groups.items():
            self.query_group_history.setdefault(query_group_id, deque(
                (), self.settings['query_group_history_length'])).append(
                    query_group[self.peer_id].reputation)

    def handle_request(self, queried_id):
        try:
            for pending_queried_id in self.pending_queries:
                if pending_queried_id.startswith(queried_id):
                    status = 'pending'
                    return
            if queried_id == self.peer_id:
                status = 'own_id'
                return
            for sync_peer_id in self.sync_peers:
                if sync_peer_id.startswith(queried_id):
                    # TODO Actually send query in case queried_id is a prefix.
                    # This behavior is useless for the purpose of finding more
                    # sync peers.
                    # TODO Also check if the peer is already known from a query
                    # group.
                    status = 'known'
                    return
            status = 'querying'
        finally:
            in_event_id = self.logger.log(an.Request(self.env.now,
                                                     self.peer_id, queried_id,
                                                     status))
        self.recv_query(self.peer_id, queried_id, in_event_id, skip_log=True)

    def send_query(self, queried_id, pending_query, in_event_id):
        """
        Send a query for an ID.

        Takes the first element of pending_query.peers_to_query as recipient,
        therefore this list must not be empty. Also starts a timeout process
        and stores it in pending_query.timeout_proc.
        """
        peer_to_query_id = pending_query.peers_to_query.pop(0)
        in_event_id = self.logger.log(an.QuerySent(self.env.now, self.peer_id,
                                                   peer_to_query_id,
                                                   queried_id, in_event_id))
        timeout_proc = self.env.process(self.query_timeout(peer_to_query_id,
                                                           queried_id,
                                                           in_event_id))
        pending_query.timeout_proc = timeout_proc
        pending_query.queries_sent[peer_to_query_id] = self.env.now
        peer_to_query_address = self.lookup_address_local(peer_to_query_id)
        if peer_to_query_address is None:
            # TODO
            raise NotImplementedError('Recipient address not locally known.')
        self.network.send_query(self.peer_id, self.address,
                                peer_to_query_address, queried_id, in_event_id)

    def send_response(self, recipient_id, queried_ids, queried_peer_info,
                      in_event_id, delay=0):
        """
        :param queried_peer_info: PeerInfo object describing the peer that was
            queried. May be None to indicate no information could be found.
        """
        if not self.peer_is_known(recipient_id):
            # Don't send responses to peers we don't know. These calls can
            # happen if there was a query but before the response is sent
            # either this or the other peer leaves the query group.
            return
        assert recipient_id != self.peer_id
        if queried_peer_info is None:
            queried_peer_id = None
        else:
            queried_peer_id = queried_peer_info.peer_id
        in_event_id = self.logger.log(
            an.ResponseScheduled(self.env.now, self.env.now + delay,
                                 self.peer_id, recipient_id, queried_peer_id,
                                 queried_ids, in_event_id))
        recipient_address = self.lookup_address_local(recipient_id)
        if recipient_address is None:
            # TODO
            raise NotImplementedError('Recipient address not locally known.')
        util.do_delayed(self.env, delay, self.network.send_response,
                        self.peer_id, self.address, recipient_address,
                        queried_ids, queried_peer_info, in_event_id)

    def recv_query(self, querying_peer_id, queried_id, in_event_id,
                   skip_log=False):
        """
        :param in_event_id: The ID of the log event that caused this query to
            be received.
        :param skip_log: Whether to skip receiving this query in logging. If
            true, in_event_id will be used as the in_event_id for the query
            sending event that possibly follows.
        """
        # TODO Add the querying peer's address to the call (in a real system it
        # would be available). Decide whether to introduce the peer (would also
        # require the prefix).
        def event(status):
            return an.QueryReceived(self.env.now,
                                    querying_peer_id, self.peer_id, queried_id,
                                    status, in_event_id)
        # TODO In case of a query for a partial ID, randomize which peer is
        # returned.
        if self.peer_id.startswith(queried_id):
            if not skip_log:
                in_event_id = self.logger.log(event('own_id'))
            self.behavior.on_query_self(querying_peer_id, queried_id,
                                        in_event_id)
            return
        for sync_peer_id, sync_peer_info in self.sync_peers.items():
            if sync_peer_id.startswith(queried_id):
                if not skip_log:
                    in_event_id = self.logger.log(event('known'))
                self.behavior.on_query_sync(querying_peer_id, queried_id,
                                            sync_peer_info, in_event_id)
                return
        for pending_query_id, pending_query in self.pending_queries.items():
            if pending_query_id.startswith(queried_id):
                if not skip_log:
                    in_event_id = self.logger.log(event('pending'))
                # There already is a query for a fitting ID in progress, just
                # note to also send a response to this querying peer.
                pending_query.querying_peers.setdefault(
                    querying_peer_id, SortedIterSet()).add(queried_id)
                return
        if not skip_log:
            in_event_id = self.logger.log(event('querying'))
        self.behavior.on_query(querying_peer_id, queried_id, in_event_id)

    def recv_response(self, responding_peer_id, queried_ids, queried_peer_info,
                      in_event_id):
        """
        :param queried_peer_info: PeerInfo object describing the peer that was
            queried. May be None to indicate no information could be found.
        """
        def event(status):
            if queried_peer_info is None:
                queried_peer_id = None
            else:
                queried_peer_id = queried_peer_info.peer_id
            return an.ResponseReceived(self.env.now,
                                       responding_peer_id, self.peer_id,
                                       queried_peer_id, queried_ids,
                                       status, in_event_id)
        # Tuples of queried ID and associated pending query.
        qid_pqs = []
        for queried_id in queried_ids:
            pending_query = self.pending_queries.get(queried_id)
            if pending_query is not None:
                qid_pqs.append((queried_id, pending_query))
        for qid1, qid2 in it.product((qid for qid, _ in qid_pqs), repeat=2):
            if qid1 == qid2:
                continue
            assert qid1.startswith(qid2) or qid2.startswith(qid1)
            assert len(qid1) != len(qid2)
        if not qid_pqs:
            # This is not a response to a currently pending query.
            statuses = [self.check_completed_queries(responding_peer_id,
                                                     qid, queried_peer_info)
                        for qid in queried_ids]
            not_none_statuses = [s for s in statuses if s is not None]
            if not not_none_statuses:
                in_event_id = self.logger.log(event('unmatched'))
            else:
                for status in not_none_statuses:
                    in_event_id = self.logger.log(event(status))
            return
        retry_qid_pqs = []
        for queried_id, pending_query in qid_pqs:
            if responding_peer_id not in pending_query.queries_sent:
                status = self.check_completed_queries(
                    responding_peer_id, queried_id, queried_peer_info)
                if status is None:
                    status = 'wrong_responder'
                in_event_id = self.logger.log(event(status))
                continue
            pending_query.timeout_proc.interrupt()
            if queried_peer_info is not None:
                in_event_id = self.logger.log(event('success'))
                self.behavior.on_response_success(
                    pending_query, responding_peer_id, queried_peer_info,
                    in_event_id)
                self.pending_queries.pop(queried_id, None)
                self.archive_completed_query(pending_query, queried_id)
                self.introduce(queried_peer_info)
                continue
            if not self.pending_query_has_known_query_peer(pending_query):
                in_event_id = self.logger.log(event('failure_ultimate'))
                self.behavior.on_response_failure(
                    pending_query, responding_peer_id, in_event_id)
                self.pending_queries.pop(queried_id, None)
                self.archive_completed_query(pending_query, queried_id)
                continue
            retry_qid_pqs.append((queried_id, pending_query))
        if retry_qid_pqs:
            in_event_id = self.logger.log(event('failure_retry'))
            # Only retry the longest of the queried IDs, but add the others to
            # the pending query.
            queried_id, pending_query = max(retry_qid_pqs,
                                            key=lambda t: len(t[0]))
            for qid, pq in retry_qid_pqs:
                if qid == queried_id:
                    continue
                for qpid, qids in pq.querying_peers.items():
                    pending_query.querying_peers.setdefault(
                        qpid, SortedIterSet()).update(qids)
                self.pending_queries.pop(qid, None)
                self.archive_completed_query(pq, qid)
            self.behavior.on_response_retry(pending_query, responding_peer_id,
                                            queried_id, in_event_id)

    def send_reputation_update(self, peer_id, reputation_diff, in_event_id):
        """
        :param reputation_diff: The reputation increase that should be applied.
            Negative values mean a penalty.
        """
        assert self.peer_id != peer_id
        query_groups = list(self.peer_query_groups(peer_id))
        if not query_groups:
            self.logger.log(an.QueryPeerVanished(
                self.env.now, self.peer_id, peer_id, in_event_id))
            return
        query_group_ids = SortedIterSet(qg.query_group_id
                                        for qg in query_groups)
        query_peer_ids = SortedIterSet(pi for qg in query_groups for pi in qg)

        # Update the reputation in the shared all_query_groups. This needs to
        # be kept current since it's taken as the initial value whenever
        # someone joins a query group.
        for query_group_id in query_group_ids:
            query_peer_info = self.all_query_groups[query_group_id][peer_id]
            new_rep = max(0, query_peer_info.reputation + reputation_diff)
            query_peer_info.reputation = new_rep

        in_event_id = self.logger.log(
            an.ReputationUpdateSent(self.env.now, self.peer_id, query_peer_ids,
                                    peer_id, reputation_diff, query_group_ids,
                                    in_event_id))
        for query_peer_id in query_peer_ids:
            address = self.lookup_address_local(query_peer_id)
            self.network.send_reputation_update(
                self.peer_id, self.address, address, peer_id, query_group_ids,
                reputation_diff, self.env.now, in_event_id)

    def recv_reputation_update(self, sender_id, peer_id, query_group_ids,
                               reputation_diff, time, in_event_id):
        """
        :param query_group_ids: The IDs of the query groups in which the peer's
            reputation should be updated.
        :param time: The time at which the update is meant to be applied.
        """
        assert sender_id != peer_id
        self.logger.log(an.ReputationUpdateReceived(
            self.env.now, sender_id, self.peer_id, peer_id, reputation_diff,
            in_event_id))
        expected = self.possibly_remove_expected_penalty(
            sender_id, peer_id, reputation_diff, in_event_id)
        if peer_id == self.peer_id and reputation_diff < 0 and not expected:
            self.logger.log(an.UnexpectedPenaltyApplied(
                self.env.now, self.peer_id, sender_id, in_event_id))
        query_groups = SortedIterSet(self.query_groups[gid]
                                     for gid in query_group_ids
                                     if gid in self.query_groups
                                     and peer_id in self.query_groups[gid])
        for query_group in query_groups:
            query_peer_info = query_group[peer_id]
            # Roll back younger updates.
            younger_updates = []
            while (query_peer_info.reputation_updates
                   and query_peer_info.reputation_updates[-1][0] > time):
                younger_updates.insert(
                    0, query_peer_info.reputation_updates.pop())
                query_peer_info.reputation = younger_updates[0].old_reputation
            # Do the update.
            query_peer_info.reputation_updates.append(
                ReputationUpdate(time, query_peer_info.reputation,
                                 reputation_diff))
            new_rep = calculate_reputation(
                self.settings['reward_attenuation'],
                query_peer_info.reputation, reputation_diff)
            # Reapply rolled back updates.
            for update in younger_updates:
                new_update = ReputationUpdate(update.time, new_rep,
                                              update.reputation_diff)
                new_rep = calculate_reputation(
                    self.settings['reward_attenuation'], new_rep,
                    update.reputation_diff)
                query_peer_info.reputation_updates.append(new_update)
            query_peer_info.reputation = new_rep
            # Prune old updates. This must not be done too eagerly, as it could
            # otherwise result in desynchronization of the reputation record
            # between peers.
            del_idx = next((i + 1 for (i, update)
                            in enumerate(query_peer_info.reputation_updates)
                            if update.time < self.env.now
                            - self.settings['update_retention_time']), 0)
            del query_peer_info.reputation_updates[:del_idx]

    def finalize_query(self, status, in_event_id):
        self.logger.log(an.QueryFinalized(self.env.now, self.peer_id, status,
                                          in_event_id))

    def check_completed_queries(self, responding_peer_id, queried_id,
                                queried_peer_info):
        """
        Check the list of already completed queries for a match.

        Checks whether responding_peer has previously been queried for
        queried_id but that query has already been answered by someone else.
        This is done by checking the completed_queries dictionary, into which
        PendingQuery objects are placed once a query is answered. Also removes
        that entry.

        Return None if there was no matching entry, 'late_success' if there was
        and the query was a success, and 'late_failure' if the response reports
        failure.
        """
        completed_queries = self.completed_queries.get(queried_id)
        if completed_queries is None:
            return
        for i, pending_query in enumerate(completed_queries):
            sent_query = pending_query.queries_sent.pop(responding_peer_id,
                                                        None)
            if sent_query is None:
                # This particular pending query was not sent toresponding_peer.
                continue
            if queried_peer_info is not None:
                status = 'late_success'
                self.behavior.on_response_late_success(responding_peer_id)
            else:
                status = 'late_failure'
                self.behavior.on_response_late_failure(responding_peer_id)
            break
        else:
            return None
        if len(pending_query.queries_sent) == 0:
            completed_queries.pop(i)
        if len(completed_queries) == 0:
            self.completed_queries.pop(queried_id, None)
        return status

    def archive_completed_query(self, pending_query, queried_id):
        if len(pending_query.queries_sent) == 0:
            return
        completed_queries = self.completed_queries.get(queried_id)
        if completed_queries is not None:
            completed_queries.append(pending_query)
        else:
            self.completed_queries[queried_id] = [pending_query]
        util.do_delayed(
            self.env, self.settings['completed_query_retention_time'],
            self.remove_completed_query, pending_query, queried_id)

    def remove_completed_query(self, pending_query, queried_id):
        completed_queries = self.completed_queries.get(queried_id)
        if completed_queries is None:
            return
        try:
            completed_queries.remove(pending_query)
        except ValueError:
            pass
        if len(completed_queries) == 0:
            self.completed_queries.pop(queried_id, None)

    def query_timeout(self, recipient_id, queried_id, in_event_id):
        def event(status):
            return an.Timeout(self.env.now, self.peer_id, recipient_id,
                              queried_id, status, in_event_id)
        timeout = (self.settings['query_timeout']
                   + self.behavior.expect_delay(recipient_id))
        try:
            yield self.env.timeout(timeout)
        except simpy.Interrupt:
            return
        pending_query = self.pending_queries.get(queried_id)
        # pending_query shouldn't be None here. When the timeout is started, it
        # must be added to the pending queries, and is only removed once a
        # response has been received and the timeout is interrupted.
        assert pending_query is not None
        if not self.pending_query_has_known_query_peer(pending_query):
            in_event_id = self.logger.log(event('failure_ultimate'))
            self.behavior.on_timeout_failure(pending_query, recipient_id,
                                             in_event_id)
            self.pending_queries.pop(queried_id, None)
            self.archive_completed_query(pending_query, queried_id)
            return
        in_event_id = self.logger.log(event('failure_retry'))
        self.behavior.on_timeout_retry(pending_query, recipient_id,
                                       queried_id, in_event_id)

    def add_pending_query(self, queried_id, pending_query):
        for pending_queried_id in self.pending_queries.keys():
            # A pending query must not be added if there is already a pending
            # query for a more specific ID.
            assert not pending_queried_id.startswith(queried_id)
        self.pending_queries[queried_id] = pending_query

    def peer_query_groups(self, peer_id):
        """Iterate query groups that contain a peer."""
        # TODO Maintain a map of all peers so we don't have to iterate over all
        # groups.
        return (g for g in self.query_groups.values()
                if peer_id in g.members())

    def known_query_peers(self):
        """
        Iterate known query peers.

        The generated elements are tuples of query group ID and QueryPeerInfo
        objects.

        Not guaranteed to be unique in regards to peers, will contain peers
        multiple times if they share multiple query groups.
        """
        return ((gid, pi)
                for gid, g in self.query_groups.items()
                for pi in g.infos()
                if pi.peer_id != self.peer_id)

    def estimated_usefulness_in(self, query_group_id):
        """Estimates the usefulness of this peer in a query group."""
        # TODO Don't use all_query_groups.
        if self.settings['usefulness'] == 'none':
            return 0
        elif self.settings['usefulness'] == 'subprefix_constant':
            usefulness = 0
            for qpi in self.all_query_groups[query_group_id].infos():
                for sp in subprefixes(qpi.prefix):
                    if self.prefix.startswith(sp):
                        # This peer is eligible to receive queries for IDs
                        # beginning with sp.
                        # TODO consider competition from other peers in the
                        # group.
                        # TODO consider prefix length. longer more useful?
                        usefulness += 1
                        break
            return usefulness
        else:
            raise Exception('Invalid usefulness setting {}.'
                            .format(self.settings['usefulness']))

    def max_peer_reputation(self, rep_peer_id, group_peer_id):
        """
        Return the maximum reputation a peer has in shared query groups.

        Out of all the query groups shared known to this peer containing both
        peers whose IDs are the arguments, return the maximum reputation of
        rep_peer.

        If there is no such query group, return 0.
        """
        # TODO Handle the case if the peer is not in a query group. That can
        # happen if a sync peer is sending out a prefix query to all known
        # peers in order to complete his subprefix connectivity. Currently,
        # when computing the reputation, the default=0 treats queries from sync
        # peers  as though they are to be maximally penalized. Obviously, there
        # needs to be a reputation mechanism for sync peers that this method
        # honors once the sync group management is actually handled by the
        # peers via  messages.
        return max((g[rep_peer_id].reputation
                    for g in self.peer_query_groups(group_peer_id)), default=0)

    def min_peer_reputation(self, peer_id):
        """
        Return the minimum reputation a peer has in any shared query group.

        If no groups are shared, return 0.
        """
        return min((g[peer_id].reputation for g in
                    self.peer_query_groups(peer_id)), default=0)

    def expected_min_reputation(self, peer_id):
        """
        Return the minimum expected future reputation perceived by a peer.

        For all the query groups shared with the peer with the given ID, return
        lowest of the expected reputations. The expected reputation consists of
        the current reputation but also considers penalties that are expected
        to be applied by others because of misbehavior.

        If no groups are shared, return 0.
        """
        min_reps = []
        for query_group in self.peer_query_groups(peer_id):
            total_expected_penalties = 0
            for qpi in query_group.infos():
                expected_penalties = self.clear_timed_out_expected_penalties(
                    qpi.peer_id)
                total_expected_penalties += sum(ep[1]
                                                for ep in expected_penalties)
            min_reps.append(query_group[self.peer_id].reputation
                            + total_expected_penalties)
        return min(min_reps, default=0)

    def clear_timed_out_expected_penalties(self, peer_id):
        """
        Clear timed out entries from expected penalties by a peer.

        Returns the cleared list.
        """
        expected_penalties = self.expected_penalties.get(peer_id, [])
        i = 0
        while i < len(expected_penalties):
            expected_penalty = expected_penalties[i]
            if self.env.now > expected_penalty[0]:
                self.logger.log(an.ExpectedPenaltyTimeout(
                    self.env.now, self.peer_id, peer_id, expected_penalty[2]))
                expected_penalties.pop(i)
            i += 1
        return expected_penalties

    def expect_penalty(self, peer_id, penalty, timeout, in_event_id):
        """
        Record a penalty that is expected to be applied in the future.

        :param peer_id: The ID of the peer who is expected to apply the
            penalty.
        :param penalty: The penalty that is expected. Should be negative, since
            it's added, not subtracted.
        :param timeout: The amount of time units after which the expected
            penalty should be considered timed out.
        """
        in_event_id = self.logger.log(an.ExpectedPenalty(
            self.env.now, self.peer_id, peer_id, in_event_id))
        self.expected_penalties.setdefault(peer_id, []).append(
            (self.env.now + timeout, penalty, in_event_id))

    def possibly_remove_expected_penalty(self, sender_id, peer_id,
                                         reputation_diff, in_event_id):
        """
        Remove an expected penalty, if applicable.

        Checks whether peer_id is the own ID, so every update can be passed in.
        Returns whether the penalty was expected.
        """
        if peer_id != self.peer_id:
            return False
        expected_penalties = self.clear_timed_out_expected_penalties(sender_id)
        i = 0
        while i < len(expected_penalties):
            if expected_penalties[i][1] == reputation_diff:
                self.logger.log(an.ExpectedPenaltyApplied(
                    self.env.now, self.peer_id, sender_id, in_event_id))
                expected_penalties.pop(i)
                return True
            i += 1
        return False


def calculate_reputation(reward_attenuation_strategy, current_reputation,
                         reputation_diff):
    """
    Calculate new reputation after a reputation update.

    :param reward_attenuation_strategy: The reward_attenuation settings
        describing the strategy to be used.
    """
    def add_attenuated_repuation(unattenuate_rep, attenuate_rep):
        lower_bound = reward_attenuation_strategy['lower_bound']
        upper_bound = reward_attenuation_strategy['upper_bound']
        assert lower_bound >= 0
        assert lower_bound <= upper_bound
        assert upper_bound > 0
        unattenuated_rep = min(current_reputation, lower_bound)
        attenuated_rep = current_reputation - unattenuated_rep
        raw_rep = unattenuate_rep(attenuated_rep)
        unattenuated_rep += reputation_diff
        raw_rep += max(unattenuated_rep - lower_bound, 0)
        unattenuated_rep = min(unattenuated_rep, lower_bound)
        attenuated_rep = attenuate_rep(raw_rep)
        return min(unattenuated_rep + attenuated_rep, upper_bound)

    if reputation_diff <= 0 or reward_attenuation_strategy['type'] == 'none':
        new_rep = current_reputation + reputation_diff
    elif reward_attenuation_strategy['type'] == 'constant':
        coefficient = reward_attenuation_strategy['coefficient']
        assert coefficient > 0 and coefficient <= 1
        new_rep = add_attenuated_repuation(lambda a: a / coefficient,
                                           lambda r: r * coefficient)
    elif reward_attenuation_strategy['type'] == 'exponential':
        coefficient = reward_attenuation_strategy['coefficient']
        exponent = reward_attenuation_strategy['exponent']
        assert coefficient > 0
        new_rep = add_attenuated_repuation(
            lambda a: (a / coefficient) ** (1 / exponent),
            lambda r: coefficient * (r ** exponent))
    elif reward_attenuation_strategy['type'] == 'harmonic':
        a = reward_attenuation_strategy['a']
        k = reward_attenuation_strategy['k']
        assert a > 0
        assert k > 0

        def unattenuate_rep(attenuated_rep):
            acc = 0
            i = 0
            raw_rep = 0
            while attenuated_rep - acc > 1:
                denominator = a + i * k
                raw_rep += denominator
                acc += 1
                i += 1
            denominator = a + i * k
            return raw_rep + (denominator * (attenuated_rep - acc))

        def attenuate_rep(raw_rep):
            attenuated_rep = 0
            i = 0
            denominator = a + i * k
            while raw_rep > denominator:
                attenuated_rep += 1
                raw_rep -= denominator
                i += 1
                denominator = a + i * k
            return attenuated_rep + (raw_rep / denominator)
        new_rep = add_attenuated_repuation(unattenuate_rep, attenuate_rep)
    else:
        raise Exception('Invalid reward attenuation type {}'
                        .format(reward_attenuation_strategy['type']))
    return max(0, new_rep)


def subprefixes(prefix):
    """
    Return an ordered list of the subprefixes for a prefix.

    A subprefix is a k-bit bitstring with k > 0, k <= len(prefix), in which the
    first k-1 bits are equal to the first k-1 bits in the prefix, and the k-th
    bit is inverted.

    The list is sorted by the length of the subprefix, in ascending order.
    """
    return [prefix[:i] + ~(prefix[i:i+1]) for i in range(len(prefix))]


class QueryGroup:
    def __init__(self, query_group_id, members, initial_reputation):
        """
        Create a query group with some initial members.

        :param members: An iterable of PeerInfo objects.
        """
        self.query_group_id = query_group_id
        self._members = OrderedDict((info.peer_id,
                                     QueryPeerInfo(info, initial_reputation))
                                    for info in members)

    def __len__(self):
        return self._members.__len__()

    def __getitem__(self, key):
        return self._members.__getitem__(key)

    def __setitem__(self, key, value):
        return self._members.__setitem__(key, value)

    def __delitem__(self, key):
        return self._members.__delitem__(key)

    def __iter__(self):
        return self._members.__iter__()

    def __contains__(self, key):
        return self._members.__contains__(key)

    def __lt__(self, other):
        return self.query_group_id < other.query_group_id

    def members(self):
        return self._members.keys()

    def items(self):
        return self._members.items()

    def infos(self):
        return self._members.values()

    def update(self, *args):
        return self._members.update(*args)

    def get(self, key, default=None):
        return self._members.get(key, default)


class PeerInfo:
    def __init__(self, peer_id, prefix, address):
        self.peer_id = peer_id
        self.prefix = prefix
        self.address = address

    def __lt__(self, other):
        return self.peer_id < other.peer_id


ReputationUpdate = namedtuple('ReputationUpdate', ['time', 'old_reputation',
                                                   'reputation_diff'])


class QueryPeerInfo(PeerInfo):
    def __init__(self, info, initial_reputation):
        super().__init__(info.peer_id, info.prefix, info.address)
        self.reputation = initial_reputation
        self.reputation_updates = []


class PendingQuery:
    def __init__(self, start_time, querying_peer_id, queried_id,
                 peers_to_query, timeout_proc=None):
        self.start_time = start_time
        self.querying_peers = OrderedDict(((querying_peer_id,
                                           SortedIterSet((queried_id,))),))
        self.timeout_proc = timeout_proc
        self.peers_to_query = peers_to_query
        # Maps ID of recipient of a query to the time the query was sent.
        self.queries_sent = OrderedDict()
