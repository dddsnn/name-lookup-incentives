import analyze as an
import util
import simpy
import itertools as it
import copy
import collections as cl
import random
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
        self.peer.send_response(querying_peer_id, queried_id, self.peer.info(),
                                in_event_id, delay=delay)

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
        self.peer.send_response(querying_peer_id, queried_id, sync_peer_info,
                                in_event_id, delay=delay)

    def on_query_external(self, querying_peer_id, queried_id, in_event_id,
                          query_further=False, query_sync=False,
                          excluded_peer_ids=util.SortedBitsTrie()):
        """
        React to a query in the case that an external query is necessary.

        A peer will only react if he has not enough reputation in one of the
        query groups shared with the querying peer. How much reputation is
        enough is governed by the no_penalty_reputation and the
        reputation_buffer_factor in the settings.

        A peer will expect penalties if he misbehaves.

        The recipient of a possible query is chosen using
        select_peer_to_query().

        :param excluded_peer_ids: A trie whose keys are peer IDs that should
            not be returned or prefixes that should not be prefixes of the peer
            that is returned. Useful for finding new peers with a certain
            prefix while avoiding learning about peers that are already known.
        """
        if self.peer.has_in_query(querying_peer_id, queried_id,
                                  excluded_peer_ids):
            # The querying peer has already queried for this exact ID. This may
            # happen when find_missing_query_peers() calls this directly. Don't
            # record this again.
            assert querying_peer_id == self.peer_id
            return
        in_query = self.peer.get_in_query(querying_peer_id, queried_id)
        if self.peer.has_matching_out_queries(queried_id, excluded_peer_ids):
            # There's a query going on that should provide an answer.
            if in_query is not None:
                # Peers are at the moment unable to deal with multiple incoming
                # queries from the same peer for the same ID if only the
                # excluded IDs differ. In this case, don't add a new one (which
                # would overwrite the old one), only update the old one's
                # excluded peers. This is a workaround analogous to the one
                # below avoiding multiple outgoing queries.
                in_query.excluded_peer_ids.update(excluded_peer_ids)
            else:
                self.peer.add_in_query(querying_peer_id, queried_id,
                                       excluded_peer_ids)
            return
        rep = self.peer.expected_min_reputation(querying_peer_id)
        enough_rep = (self.peer.settings['reputation_buffer_factor']
                      * self.peer.settings['no_penalty_reputation'])
        delay = self.decide_delay(querying_peer_id)
        if querying_peer_id != self.peer.peer_id and rep >= enough_rep:
            # We have enough reputation and are not interested in expending
            # resources into answering the query.
            self.peer.expect_penalty(
                querying_peer_id, self.peer.settings['timeout_query_penalty'],
                delay + self.peer.settings['expected_penalty_timeout_buffer'],
                in_event_id)
            return
        # TODO Send queries to multiple peers at once.
        # Initialize the set of peers that should not be queried with those to
        # whom a query for the exact ID is already in progress. This is to
        # remedy an issues arising from peers being unable to track multiple
        # queries for the same ID to the same peer. This isn't ideal, but
        # wouldn't happen often anyway.
        peers_already_queried = self.peer.out_query_recipients(queried_id)
        if self.attempt_query(queried_id, peers_already_queried, query_further,
                              query_sync, excluded_peer_ids, in_event_id):
            if in_query is not None:
                in_query.excluded_peer_ids.update(excluded_peer_ids)
            else:
                self.peer.add_in_query(querying_peer_id, queried_id,
                                       excluded_peer_ids)
            return
        # No known peer, query is impossible.
        if querying_peer_id == self.peer.peer_id:
            self.peer.finalize_own_query('impossible', in_event_id)
        else:
            self.peer.expect_penalty(
                querying_peer_id, self.peer.settings['failed_query_penalty'],
                delay + self.peer.settings['expected_penalty_timeout_buffer'],
                in_event_id)
            self.peer.send_response(
                querying_peer_id, queried_id, None, in_event_id, delay=delay)

    def on_response_success(self, responding_peer_id, queried_id,
                            queried_peer_info, excluded_peer_ids, in_event_id):
        """React to a successful response arriving."""
        self.do_rep_success(responding_peer_id, in_event_id)
        matching_in_queries = self.peer.matching_in_queries(queried_id,
                                                            excluded_peer_ids)
        self.respond_to_in_queries(matching_in_queries, queried_peer_info,
                                   in_event_id)
        self.peer.finalize_in_queries(matching_in_queries, 'success',
                                      in_event_id)

    def on_response_failure(self, responding_peer_id, queried_id,
                            peers_already_queried, query_further, query_sync,
                            excluded_peer_ids, in_event_id):
        """
        React to a failed response arriving.

        A response has failed if the responding peer is unable to either
        provide the correct record or to say that there doesn't exist one.

        Attempts to retry the query, while not querying any of the peers in
        peers_already_queried.
        """
        self.do_rep_failure(responding_peer_id, in_event_id)
        matching_in_queries = self.peer.matching_in_queries(queried_id,
                                                            excluded_peer_ids)
        if len(matching_in_queries) == 0:
            # No incoming queries could be answered by this, don't retry.
            return
        # Assure no peer to whom a query for the exact ID is currently in
        # progress get s queried again. See comment in on_query_external().
        peers_already_queried |= self.peer.out_query_recipients(queried_id)
        if self.attempt_query(queried_id, peers_already_queried, query_further,
                              query_sync, excluded_peer_ids, in_event_id):
            return
        self.respond_to_in_queries(
            matching_in_queries, None, in_event_id,
            expected_penalty=self.peer.settings['failed_query_penalty'])
        self.peer.finalize_in_queries(matching_in_queries, 'failure',
                                      in_event_id)

    def on_timeout(self, queried_peer_id, queried_id, peers_already_queried,
                   query_further, query_sync, excluded_peer_ids, in_event_id):
        """
        React to a query timing out.

        Attempts to retry the query, while not querying any of the peers in
        peers_already_queried.
        """
        self.do_rep_timeout(queried_peer_id, in_event_id)
        matching_in_queries = self.peer.matching_in_queries(queried_id,
                                                            excluded_peer_ids)
        if len(matching_in_queries) == 0:
            # No incoming queries could be answered by this, don't retry.
            return
        # Assure no peer to whom a query for the exact ID is currently in
        # progress get s queried again. See comment in on_query_external().
        peers_already_queried |= self.peer.out_query_recipients(queried_id)
        if self.attempt_query(queried_id, peers_already_queried, query_further,
                              query_sync, excluded_peer_ids, in_event_id):
            return
        self.respond_to_in_queries(
            matching_in_queries, None, in_event_id,
            expected_penalty=self.peer.settings['failed_query_penalty'])
        self.peer.finalize_in_queries(matching_in_queries, 'timeout',
                                      in_event_id)

    def attempt_query(self, queried_id, peers_already_queried, query_further,
                      query_sync, excluded_peer_ids, in_event_id):
        """
        Attempt to send a query to the next best peer.

        Return whether a query was sent.
        """
        recipient_id = self.select_peer_to_query(
            queried_id, peers_already_queried, query_further, query_sync,
            excluded_peer_ids)
        if recipient_id is not None:
            self.peer.send_query(
                recipient_id, queried_id, peers_already_queried, query_further,
                query_sync, excluded_peer_ids, in_event_id)
            return True
        return False

    def respond_to_in_queries(self, in_queries_map, queried_peer_info,
                              in_event_id, expected_penalty=None):
        """
        Respond to incoming queries.

        Chooses an appropriate delay.

        :param in_queries_map: A map mapping queried ID to maps mapping
            querying peer ID to IncomingQuery objects (as returned by
            Peer.matching_in_queries()).
        """
        for in_queried_id, in_queries in in_queries_map.items():
            for querying_peer_id, in_query in in_queries.items():
                # TODO Make it possible for on_response_failure() and
                # on_timeout() to not send a fail response in case there are
                # some outgoing queries that would answer this query. But they
                # should only do so if the response is not likely going to be
                # late.
                time_taken = self.peer.env.now - in_query.time
                delay = max(
                    0, self.decide_delay(querying_peer_id) - time_taken)
                if expected_penalty is not None:
                    self.peer.expect_penalty(
                        querying_peer_id, expected_penalty,
                        self.peer.settings['expected_penalty_timeout_buffer']
                        + delay, in_event_id)
                self.peer.send_response(querying_peer_id, in_queried_id,
                                        queried_peer_info, in_event_id,
                                        delay=delay)

    # TODO Add a way to react to a query this peer is supposed to answer being
    # about to time out. The peer should respond with a fail response and incur
    # the penalty for that rather than one for a timeout (which should be
    # higher).

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
        if querying_peer_id == self.peer.peer_id:
            return 0
        max_rep = self.peer.max_peer_reputation(querying_peer_id,
                                                querying_peer_id)
        npr = self.peer.settings['no_penalty_reputation']
        return min(max(npr - max_rep, 0), npr)

    def expect_delay(self, peer_to_query_id):
        """Predict the penalty delay that will be imposed."""
        if peer_to_query_id == self.peer.peer_id:
            return 0
        max_rep = self.peer.max_peer_reputation(self.peer.peer_id,
                                                peer_to_query_id)
        npr = self.peer.settings['no_penalty_reputation']
        return min(max(npr - max_rep, 0), npr)

    def select_peer_to_query(self, queried_id, peers_already_queried,
                             query_further, query_sync, excluded_peer_ids):
        """
        Select the next peer to query.

        Considers peers that could be queried to resolve queried_id and returns
        the ID of the best one according to best_peer_to_query(). Does not
        consider peers whose IDs are in peers_already_queried. Does not
        consider peers if a prefix of their ID is in the key set of
        excluded_peer_ids, unless query_further is True.

        Returns the ID of the peer that should be queried, or None if there is
        no peer that could be queried.

        :param query_further: If True, also considers peers whose overlap with
            the queried ID is less than or equal than for this peer, otherwise
            only those where it is greater.
        :param query_sync: If True, also considers sync peers.
        """
        peers_to_query_info = []
        if query_sync:
            peers_to_query_info += [
                (True, pi) for pi in self.peer.sync_peers.values()
                if pi.peer_id != self.peer.peer_id
                and pi.peer_id not in peers_already_queried
                and (query_further
                     or not excluded_peer_ids.has_prefix_of(pi.peer_id))]
        if query_further:
            peers_to_query_info += [
                (False, pi) for _, pi in self.peer.known_query_peers()
                if pi.peer_id not in peers_already_queried]
        else:
            own_overlap = util.bit_overlap(self.peer.prefix, queried_id)
            for _, query_peer_info in self.peer.known_query_peers():
                # OPTI Range queries for performance.
                if (util.bit_overlap(query_peer_info.prefix, queried_id)
                        > own_overlap
                        and query_peer_info.peer_id
                        not in peers_already_queried
                        and not excluded_peer_ids.has_prefix_of(
                            query_peer_info.peer_id)):
                    peers_to_query_info.append((False, query_peer_info))
        if len(peers_to_query_info) == 0:
            return None
        return self.best_peer_to_query(peers_to_query_info, queried_id)

    def best_peer_to_query(self, sync_peer_infos, queried_id):
        """
        Get the best out of a list of PeerInfos.

        The selected peer depends on the query_peer_selection value in the
        settings. Possible values are:
            * 'overlap': Choose the peer whose prefix has the highest overlap
                with queried_id. No tie breaker.
            * 'overlap_high_rep_last': As 'overlap', but peers with enough
                reputation (i.e. whose minimum reputation in all shared query
                groups is greater than or equal 'no_penalty_reputation' times
                'reputation_buffer_factor') are given lower priority than all
                others.
            * 'random': Choose a peer at random.
            * 'overlap_rep_sorted': As 'overlap' but within the group of the
                highest overlap, choose the peer with the lowest reputation.
            * 'rep_sorted': Choose the peer with the lowest reputation.

        For all strategies except 'random', sync peers are given lower priority
        than query peers.

        Returns just the peer ID.

        :param sync_peer_infos: A list of tuples (sp, pi) describing peers,
            where sp is a boolean that is True if the peer is a sync peer and
            pi is the peer's PeerInfo. Must not be empty.
        """
        if (self.peer.settings['query_peer_selection']
                not in ('overlap', 'overlap_high_rep_last', 'random',
                        'overlap_rep_sorted', 'rep_sorted')):
            raise Exception(
                'Invalid query peer selection strategy {}.'
                .format(self.peer.settings['query_peer_selection']))
        if (self.peer.settings['query_peer_selection']
                in ('overlap', 'overlap_high_rep_last', 'overlap_rep_sorted')):
            def overlap_key(sync_peer_info):
                sync_peer, peer_info = sync_peer_info
                overlap = util.bit_overlap(peer_info.prefix, queried_id)
                return (-int(sync_peer), overlap)
            if self.peer.settings['query_peer_selection'] == 'overlap':
                return max(sync_peer_infos, key=overlap_key)[1].peer_id
            elif (self.peer.settings['query_peer_selection']
                  == 'overlap_high_rep_last'):
                def high_rep_key(sync_peer_info):
                    ok = overlap_key(sync_peer_info)
                    enough_rep\
                        = (self.peer.settings['reputation_buffer_factor']
                           * self.peer.settings['no_penalty_reputation'])
                    min_rep = self.peer.min_peer_reputation(
                        sync_peer_info[1].peer_id)
                    if min_rep >= enough_rep:
                        return (ok[0], 0, ok[1])
                    return (ok[0], 1, ok[1])
                return max(sync_peer_infos, key=high_rep_key)[1].peer_id
            else:
                def rep_sorted_key(sync_peer_info):
                    min_rep = self.peer.min_peer_reputation(
                        sync_peer_info[1].peer_id)
                    return (*overlap_key(sync_peer_info), -min_rep)
                return max(sync_peer_infos, key=rep_sorted_key)[1].peer_id
        elif self.peer.settings['query_peer_selection'] == 'random':
            return random.choice(sync_peer_infos)[1].peer_id
        elif self.peer.settings['query_peer_selection'] == 'rep_sorted':
            def key(sync_peer_info):
                sync_peer, peer_info = sync_peer_info
                min_rep = self.peer.min_peer_reputation(peer_info.peer_id)
                return (int(sync_peer), min_rep)
            return min(sync_peer_infos, key=key)[1].peer_id

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
                covering_peer_ids = util.SortedIterSet(it.chain(*(
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
        self.query_groups = cl.OrderedDict()
        self.sync_peers = cl.OrderedDict()
        self.in_queries_map = util.SortedBitsTrie()
        self.out_queries_map = util.SortedBitsTrie()
        self.address = self.network.register(self)
        self.behavior = PeerBehavior(self)
        self.query_group_history = cl.OrderedDict()
        self.expected_penalties = cl.OrderedDict()

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
                    query_group_copy = copy.deepcopy(query_group)
                    query_group_copy[self.peer_id] = QueryPeerInfo(
                        self.info(), self.settings['initial_reputation'])
                    self.query_groups[query_group.query_group_id]\
                        = query_group_copy
                    self.all_query_groups[query_group.query_group_id]\
                        = copy.deepcopy(query_group_copy)
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
                    query_group_copy = copy.deepcopy(query_group)
                    peer.query_groups[query_group.query_group_id]\
                        = query_group_copy
                    self.all_query_groups[query_group.query_group_id]\
                        = copy.deepcopy(query_group_copy)
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
                = copy.deepcopy(query_group)
            peer.query_groups[query_group.query_group_id]\
                = copy.deepcopy(query_group)
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
                        util.SortedIterSet(query_peer.uncovered_subprefixes()),
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
        further away are also queried by calling on_query_external() directly
        with query_further set to True.

        If query_sync_for_subprefixes is set in the settings, sync peers will
        be queried as well.
        """
        for subprefix, known_peers in self.subprefix_coverage().items():
            if len(known_peers) >= self.settings['min_desired_query_peers']:
                continue
            if (self.settings['ignore_non_existent_subprefixes']
                    and len(known_peers)
                    >= self.num_known_peers_for_subprefix(subprefix)):
                assert (len(known_peers)
                        == self.num_known_peers_for_subprefix(subprefix))
                continue
            if self.has_matching_out_queries(subprefix, known_peers):
                # There is a pending query that will satisfy the subprefix
                # when successful.
                continue
            in_event_id = self.logger.log(an.UncoveredSubprefixSearch(
                self.env.now, self.peer_id, None))
            query_sync = self.settings['query_sync_for_subprefixes']
            self.behavior.on_query_external(
                self.peer_id, subprefix, in_event_id, query_further=True,
                query_sync=query_sync, excluded_peer_ids=known_peers)

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
            for sp, peers in self.subprefix_coverage().items():
                if (peer_info.prefix.startswith(sp)
                        and len(peers)
                        < self.settings['min_desired_query_peers']):
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
        Map each subprefix to the known peers serving it.

        The dictionary that is returned maps each of the possible
        len(self.prefix) subprefixes to a trie whose keys are peer IDs this
        peer knows who can serve the subprefix.
        """
        coverage = cl.OrderedDict((sp, util.SortedBitsTrie())
                                  for sp in self.subprefixes())
        for _, query_peer_info in self.known_query_peers():
            for sp in self.subprefixes():
                if query_peer_info.prefix.startswith(sp):
                    coverage[sp][query_peer_info.peer_id] = None
                    break
        return cl.OrderedDict((sp, qps) for (sp, qps) in coverage.items())

    def uncovered_subprefixes(self):
        """Return subprefixes for which no peer is known."""
        return (sp for sp, qps in self.subprefix_coverage().items()
                if len(qps) == 0)

    def num_known_peers_for_subprefix(self, subprefix):
        """
        Return the number of known peers whose prefix starts with subprefix.

        Uses the all_prefixes trie, which is global information given to the
        peer by the simulation that wouldn't be available in a real system.
        """
        return sum(1 for _ in self.all_prefixes.iterkeys(subprefix))

    def query_group_subprefix_coverage(self):
        """
        Map each query group to the subprefixes covered by peers in it.

        The dictionary that is returned maps each query group ID to a
        dictionary that maps each of the possible len(self.prefix) subprefixes
        to the set of IDs of the peers in the query group that serve that
        subprefix.
        """
        coverage = cl.OrderedDict((sp, util.SortedIterSet())
                                  for sp in self.subprefixes())
        query_group_coverage = cl.OrderedDict(
            (gid, copy.deepcopy(coverage)) for gid in self.query_groups.keys())
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
                self.query_groups[query_group_id] = copy.deepcopy(
                    self.all_query_groups[query_group_id])
                qpi = QueryPeerInfo(self.info(),
                                    self.settings['initial_reputation'])
                self.query_groups[query_group_id][self.peer_id] = qpi
                self.all_query_groups[query_group_id][self.peer_id]\
                    = copy.deepcopy(qpi)
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
            self.query_group_history.setdefault(query_group_id, cl.deque(
                (), self.settings['query_group_history_length'])).append(
                    query_group[self.peer_id].reputation)

    def handle_request(self, queried_id):
        try:
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

    def send_query(self, recipient_id, queried_id, peers_already_queried,
                   query_further, query_sync, excluded_peer_ids, in_event_id):
        """
        Send a query for an ID.

        Adds the recipient ID to peers_already_queried.

        :param peers_already_queried: A set of peer IDs that should not be
            queried.
        """
        assert (queried_id not in self.out_queries_map
                or recipient_id not in self.out_queries_map[queried_id])
        peers_already_queried.add(recipient_id)
        out_query = OutgoingQuery(self.env.now, peers_already_queried,
                                  query_further, query_sync, excluded_peer_ids)
        self.out_queries_map.setdefault(
            queried_id, cl.OrderedDict())[recipient_id] = out_query
        in_event_id = self.logger.log(an.QuerySent(
            self.env.now, self.peer_id, recipient_id, queried_id, in_event_id))
        timeout_proc = self.env.process(self.query_timeout(
            recipient_id, queried_id, in_event_id))
        out_query.timeout_proc = timeout_proc
        peer_to_query_address = self.lookup_address_local(recipient_id)
        if peer_to_query_address is None:
            # TODO
            raise NotImplementedError('Recipient address not locally known.')
        self.network.send_query(self.peer_id, self.address,
                                peer_to_query_address, queried_id,
                                excluded_peer_ids, in_event_id)

    def send_response(self, recipient_id, queried_id, queried_peer_info,
                      in_event_id, delay=0):
        """
        :param queried_peer_info: PeerInfo object describing the peer that was
            queried. May be None to indicate no information could be found. The
            fields (peer_id, prefix and address) may be None to indicate that
            there does not exist a peer matching queried_id.
        """
        if not self.peer_is_known(recipient_id):
            # Don't send responses to peers we don't know. These calls can
            # happen if there was a query but before the response is sent
            # either this or the other peer leaves the query group.
            return
        assert recipient_id != self.peer_id
        in_event_id = self.logger.log(
            an.ResponseScheduled(self.env.now, self.env.now + delay,
                                 self.peer_id, recipient_id, queried_peer_info,
                                 queried_id, in_event_id))
        recipient_address = self.lookup_address_local(recipient_id)
        if recipient_address is None:
            # TODO
            raise NotImplementedError('Recipient address not locally known.')
        util.do_delayed(self.env, delay, self.network.send_response,
                        self.peer_id, self.address, recipient_address,
                        queried_id, queried_peer_info, in_event_id)

    def recv_query(self, querying_peer_id, queried_id, in_event_id,
                   excluded_peer_ids=util.SortedBitsTrie(), skip_log=False):
        """
        :param skip_log: Whether to skip receiving this query in logging. If
            true, in_event_id will be used as the in_event_id for the query
            sending event that possibly follows.
        """
        # TODO Add the querying peer's address to the call (in a real system it
        # would be available). Decide whether to introduce the peer (would also
        # require the prefix).
        def event(status):
            return an.QueryReceived(self.env.now, querying_peer_id,
                                    self.peer_id, queried_id, status,
                                    in_event_id)
        if self.has_in_query(querying_peer_id, queried_id, excluded_peer_ids):
            if querying_peer_id == self.peer_id:
                # Peers may "send" a query to themselves again before receiving
                # an answer as part of handling the request. Just log this and
                # ignore.
                self.finalize_own_query('pending', in_event_id)
                return
            else:
                # Another peer may send a query for the exact same ID again
                # before receiving an answer if it timed out at the other peer
                # and fails ultimately (i.e. the other peer knows no other
                # peer to send the query to). In that case, the peer forgets
                # that he sent a query and is free to send it again for another
                # request or query that he receives. Update the arrival time of
                # the existing incoming query so that a response will be sent
                # with a delay appropriate to the later query.
                in_query = self.in_queries_map[queried_id][querying_peer_id]
                in_query.time = self.env.now
                return
        if (self.peer_id.startswith(queried_id)
                and not excluded_peer_ids.has_prefix_of(self.peer_id)):
            if not skip_log:
                in_event_id = self.logger.log(event('own_id'))
            self.behavior.on_query_self(querying_peer_id, queried_id,
                                        in_event_id)
            return
        if (queried_id.startswith(self.prefix)
                or self.prefix.startswith(queried_id)):
            # Query for a sync peer.
            for sync_peer_id, sync_peer_info in self.sync_peers.items():
                # OPTI Use a trie instead of iterating.
                if (sync_peer_id.startswith(queried_id)
                        and not excluded_peer_ids.has_prefix_of(
                            sync_peer_id)):
                    if not skip_log:
                        in_event_id = self.logger.log(event('known'))
                    self.behavior.on_query_sync(querying_peer_id, queried_id,
                                                sync_peer_info, in_event_id)
                    return
            # None of self or any sync peers are valid responses, even though
            # they match because they've all been excluded.
            if len(queried_id) >= len(self.prefix):
                # The queried ID is at least as long as the prefix, so we are
                # confident that we know all peers that are possible answers
                # (our sync group) and can answer that no such peer exists.
                # TODO Signal that no such peer exists.
                pass
            else:
                # The queried ID is shorter than the prefix, so we can't say
                # for sure that there is no peer matching the query, unless the
                # prefixes of all other possible sync groups have already been
                # excluded.
                # TODO Signal that no such peer exists.
                assert self.prefix not in excluded_peer_ids
                # Add this peer's prefix to the excluded IDs to signal no peer
                # exists with this peer's prefix so we don't get this query
                # back.
                excluded_peer_ids[self.prefix] = None
        # TODO Don't query if peer is known as a query peer.
        if not skip_log:
            in_event_id = self.logger.log(event('external'))
        self.behavior.on_query_external(querying_peer_id, queried_id,
                                        in_event_id,
                                        excluded_peer_ids=excluded_peer_ids)

    def recv_response(self, responding_peer_id, queried_id, queried_peer_info,
                      in_event_id):
        """
        :param queried_id: The IDs or prefix that was queried and for which
            this is the response.
        :param queried_peer_info: PeerInfo object describing the peer that was
            queried. May be None to indicate failure, i.e. the responding peer
            doesn't know the answer. The ID, prefix and the address field may
            be None to indicate that there doesn't exist a peer whose ID
            matches any of the queried IDs.
        """
        try:
            out_query = self.out_queries_map[queried_id].pop(
                responding_peer_id)
            if queried_peer_info is not None:
                assert not out_query.excluded_peer_ids.has_prefix_of(
                    queried_peer_info.peer_id)
                status = 'success'
            else:
                status = 'failure'
        except KeyError:
            status = 'unmatched'
            return
        finally:
            in_event_id = self.logger.log(an.ResponseReceived(
                self.env.now, responding_peer_id, self.peer_id,
                queried_peer_info, queried_id, status, in_event_id))
        if len(self.out_queries_map[queried_id]) == 0:
            del self.out_queries_map[queried_id]
        out_query.timeout_proc.interrupt()
        if queried_peer_info is not None:
            self.behavior.on_response_success(
                responding_peer_id, queried_id, queried_peer_info,
                out_query.excluded_peer_ids, in_event_id)
            if queried_peer_info.peer_id is not None:
                assert queried_peer_info.prefix is not None
                assert queried_peer_info.address is not None
                self.introduce(queried_peer_info)
            else:
                # TODO The responding peer claims that there doesn't exist a
                # peer with the ID we queried. Decide if we trust him or want
                # to query someone else to confirm.
                pass
            return
        self.behavior.on_response_failure(
            responding_peer_id, queried_id, out_query.peers_already_queried,
            out_query.query_further, out_query.query_sync,
            out_query.excluded_peer_ids, in_event_id)

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
        query_group_ids = util.SortedIterSet(qg.query_group_id
                                             for qg in query_groups)
        query_peer_ids = util.SortedIterSet(
            pi for qg in query_groups for pi in qg)

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
        query_groups = util.SortedIterSet(
            self.query_groups[gid] for gid in query_group_ids
            if gid in self.query_groups and peer_id in self.query_groups[gid])
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

    def query_timeout(self, peer_id, queried_id, in_event_id):
        """
        :param peer_id: ID of the peer who failed to respond in time.
        """
        timeout = (self.settings['query_timeout']
                   + self.behavior.expect_delay(peer_id))
        try:
            yield self.env.timeout(timeout)
        except simpy.Interrupt:
            return
        in_event_id = self.logger.log(an.Timeout(
            self.env.now, self.peer_id, peer_id, queried_id, in_event_id))
        # TODO Do timed out queries need to be archived in order to give
        # rewards for correct but late responses?
        assert queried_id in self.out_queries_map
        assert peer_id in self.out_queries_map[queried_id]
        out_query = self.out_queries_map[queried_id].pop(peer_id)
        if len(self.out_queries_map[queried_id]) == 0:
            del self.out_queries_map[queried_id]
        self.behavior.on_timeout(
            peer_id, queried_id, out_query.peers_already_queried,
            out_query.query_further, out_query.query_sync,
            out_query.excluded_peer_ids, in_event_id)

    def peer_query_groups(self, peer_id):
        """Iterate query groups that contain a peer."""
        # OPTI Maintain a map of all peers so we don't have to iterate over all
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
        # peers via messages.
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

    def add_in_query(self, querying_peer_id, queried_id, excluded_peer_ids):
        assert not self.has_in_query(querying_peer_id, queried_id,
                                     util.SortedBitsTrie())
        in_query = IncomingQuery(self.env.now, excluded_peer_ids)
        self.in_queries_map.setdefault(queried_id, cl.OrderedDict())[
            querying_peer_id] = in_query

    def has_in_query(self, querying_peer_id, queried_id, excluded_peer_ids):
        """
        Return whether this peer has an unfinished incoming query.

        Returns True only if there is an incoming query by the exact peer for
        the exact ID and the IncomingQuery's excluded_peer_ids has a key that
        is a prefix for every key in the excluded_peer_ids parameter.
        """
        try:
            in_query = self.in_queries_map[queried_id][querying_peer_id]
        except KeyError:
            return False
        return excluded_peer_ids.is_key_prefix_subset(
            in_query.excluded_peer_ids)

    def has_matching_out_queries(self, queried_id, excluded_peer_ids):
        """
        Return whether there are ongoing queries matching an ID.

        This is true if queries have been sent, but no response yet received,
        whose responses could answer queries for queried_id. This is the case
        if queried_id is a prefix of the queried ID of the ongoing query, i.e.
        the queried ID of the ongoing query is equal to or more specific than
        queried_id. The excluded peer IDs must also match, i.e. the
        excluded_peer_ids key set of the ongoing query must have a prefix for
        every element in the key set of the trie passed in as a parameter.
        """
        for out_queries in self.out_queries_map.itervalues(queried_id):
            for out_query in out_queries.values():
                if excluded_peer_ids.is_key_prefix_subset(
                        out_query.excluded_peer_ids):
                    return True
        return False

    def matching_in_queries(self, queried_id, excluded_peer_ids):
        """
        Find incoming queries matching an ID.

        Returns a map mapping an ID that matches queried_id to maps in which
        each item describes an incoming query, i.e. one that this peer was
        asked to answer. Each such item maps the ID of the querying peer to an
        IncomingQuery object.

        An ID matches queried_id if it is a prefix of queried_id, i.e. it is
        equal to or more general than queried_id. Additionally, the tries of
        excluded peer IDs must match, i.e. for every element in the ongoing
        incoming query's excluded_peer_ids keys there must be a prefix in the
        excluded_peer_ids parameter.

        Creates a copy of this peer's relevant in_queries_map, and doesn't
        delete anything.
        """
        res = cl.OrderedDict()
        for in_queried_id, in_queries in self.in_queries_map.iter_prefix_items(
                queried_id):
            for querying_peer_id, in_query in in_queries.items():
                if in_query.excluded_peer_ids.is_key_prefix_subset(
                        excluded_peer_ids):
                    res.setdefault(in_queried_id, cl.OrderedDict()).setdefault(
                        querying_peer_id, copy.deepcopy(in_query))
        return res

    def get_in_query(self, querying_peer_id, queried_id):
        try:
            return self.in_queries_map[queried_id][querying_peer_id]
        except KeyError:
            return None

    def out_query_recipients(self, queried_id):
        if queried_id in self.out_queries_map:
            return util.SortedIterSet(pi for pi in
                                      self.out_queries_map[queried_id].keys())
        return util.SortedIterSet()

    def finalize_own_query(self, status, in_event_id):
        self.logger.log(an.QueryFinalized(self.env.now, self.peer_id, status,
                                          in_event_id))

    def finalize_in_queries(self, in_queries_map, status, in_event_id):
        """
        Delete incoming queries and finalize own queries.

        :param in_queries_map: A map mapping queried ID to maps mapping
            querying peer ID to IncomingQuery objects (as returned by
            matching_in_queries()).
        """
        for queried_id, in_queries in in_queries_map.items():
            if self.peer_id in in_queries:
                self.finalize_own_query(status, in_event_id)
            del self.in_queries_map[queried_id]


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
        self._members = cl.OrderedDict(
            (info.peer_id, QueryPeerInfo(info, initial_reputation))
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


ReputationUpdate = cl.namedtuple('ReputationUpdate',
                                 ['time', 'old_reputation', 'reputation_diff'])


class QueryPeerInfo(PeerInfo):
    def __init__(self, info, initial_reputation):
        super().__init__(info.peer_id, info.prefix, info.address)
        self.reputation = initial_reputation
        self.reputation_updates = []


class OutgoingQuery:
    def __init__(self, time, peers_already_queried, query_further, query_sync,
                 excluded_peer_ids):
        self.time = time
        self.peers_already_queried = peers_already_queried
        self.query_further = query_further
        self.query_sync = query_sync
        self.excluded_peer_ids = excluded_peer_ids
        self.timeout_proc = None


class IncomingQuery:
    def __init__(self, time, excluded_peer_ids):
        self.time = time
        self.excluded_peer_ids = excluded_peer_ids
