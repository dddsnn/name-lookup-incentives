import analyze as an
import util
from util import SortedIterSet
from simulation import (SUCCESSFUL_QUERY_REWARD, FAILED_QUERY_PENALTY,
                        TIMEOUT_QUERY_PENALTY)
import simpy
from itertools import count
from copy import deepcopy
from collections import namedtuple, OrderedDict


query_group_id_iter = count()


class PeerBehavior:
    def __init__(self, peer):
        self.peer = peer

    def on_query_self(self, querying_peer_id, queried_id, in_event_id):
        """React to a query for own ID."""
        min_rep = min((g[self.peer.peer_id].reputation for g in
                       self.peer.peer_query_groups(querying_peer_id)),
                      default=0)
        # TODO Unhardcode
        if querying_peer_id != self.peer.peer_id and min_rep >= 15:
            return
        delay = self.decide_delay(querying_peer_id)
        info = PeerInfo(self.peer.peer_id, self.peer.prefix, self.peer.address)
        self.peer.send_response(querying_peer_id, SortedIterSet((queried_id,)),
                                info, in_event_id, delay=delay)

    def on_query_sync(self, querying_peer_id, queried_id, sync_peer_info,
                      in_event_id):
        """React to a query for the ID of a sync peer."""
        min_rep = min((g[self.peer.peer_id].reputation for g in
                       self.peer.peer_query_groups(querying_peer_id)),
                      default=0)
        # TODO Unhardcode
        if querying_peer_id != self.peer.peer_id and min_rep >= 15:
            return
        delay = self.decide_delay(querying_peer_id)
        self.peer.send_response(querying_peer_id, SortedIterSet((queried_id,)),
                                sync_peer_info, in_event_id, delay=delay)

    def on_query(self, querying_peer_id, queried_id, in_event_id,
                 query_all=False):
        """
        React to a query.

        This method implements the "good" default behavior. A list of peers is
        created that will be queried and sorted based on how close they are to
        the queried ID. A PendingQuery is created with these peers and used to
        send a query.

        By default, the peers that will be queried are only ones whose prefix
        has a larger overlap with the queried ID than this peer, i.e. who are
        closer to the target ID. However, if query_all is True, all known
        peers, including sync peers, will be queried.
        """
        min_rep = min((g[self.peer.peer_id].reputation for g in
                       self.peer.peer_query_groups(querying_peer_id)),
                      default=0)
        # TODO Unhardcode
        if querying_peer_id != self.peer.peer_id and min_rep >= 15:
            return
        if query_all:
            peers_to_query_info = (list(self.peer.known_query_peers())
                                   + list(self.peer.sync_peers.values()))
            peers_to_query_info.sort(
                key=lambda pi: util.bit_overlap(pi.prefix, queried_id),
                reverse=True)
            peers_to_query = [pi.peer_id for pi in peers_to_query_info]
        else:
            peers_to_query = self.peer.select_peers_to_query(queried_id)
        if len(peers_to_query) == 0:
            self.peer.send_response(querying_peer_id,
                                    SortedIterSet((queried_id,)), None,
                                    in_event_id,
                                    delay=self.decide_delay(querying_peer_id))
            return
        pending_query = PendingQuery(self.peer.env.now, querying_peer_id,
                                     queried_id, peers_to_query)
        self.peer.pending_queries[queried_id] = pending_query
        self.peer.send_query(queried_id, pending_query, in_event_id)
        # TODO Send queries to multiple peers at once.

    def on_response_success(self, pending_query, responding_peer_id,
                            queried_peer_info, in_event_id):
        """React to a successful response arriving."""
        queried_ids = pending_query.querying_peers.pop(self.peer.peer_id, None)
        total_time = self.peer.env.now - pending_query.start_time
        # TODO Update the ID/address mapping, even if we're just passing the
        # query result through to another peer.
        for querying_peer_id, queried_ids in (pending_query.querying_peers
                                              .items()):
            delay = max(self.decide_delay(querying_peer_id) - total_time, 0)
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
        queried_ids = pending_query.querying_peers.get(self.peer.peer_id)
        total_time = self.peer.env.now - pending_query.start_time
        for querying_peer_id, queried_ids in (pending_query.querying_peers
                                              .items()):
            delay = max(self.decide_delay(querying_peer_id) - total_time, 0)
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
        queried_ids = pending_query.querying_peers.get(self.peer.peer_id)
        total_time = self.peer.env.now - pending_query.start_time
        for querying_peer_id, queried_ids in (pending_query.querying_peers
                                              .items()):
            delay = max(self.decide_delay(querying_peer_id) - total_time, 0)
            self.peer.send_response(querying_peer_id, queried_ids, None,
                                    in_event_id, delay=delay)
        self.do_rep_timeout(recipient_id, in_event_id)

    def on_timeout_retry(self, pending_query, recipient_id, queried_id,
                         in_event_id):
        """React to a query timing out that can be retried."""
        self.peer.send_query(queried_id, pending_query, in_event_id)
        self.do_rep_timeout(recipient_id, in_event_id)

    def do_rep_success(self, peer_id, in_event_id):
        """Do the reputation update after a successful query."""
        self.peer.send_reputation_update(peer_id, SUCCESSFUL_QUERY_REWARD,
                                         in_event_id)

    def do_rep_failure(self, peer_id, in_event_id):
        """Do the reputation update after a failed query."""
        self.peer.send_reputation_update(peer_id, FAILED_QUERY_PENALTY,
                                         in_event_id)

    def do_rep_timeout(self, peer_id, in_event_id):
        """Do the reputation update after a timed out query."""
        self.peer.send_reputation_update(peer_id, TIMEOUT_QUERY_PENALTY,
                                         in_event_id)

    def decide_delay(self, querying_peer_id):
        """Decide what penalty delay to impose."""
        # TODO Handle the case if querying_peer is not in a query group. That
        # can happen if a sync peer is sending out a prefix query to all known
        # peers in order to complete his subprefix connectivity. Currently,
        # when computing max_rep, the default=0 treats queries from sync_peers
        # as though they are to be maximally penalized. Obviously, there needs
        # to be a reputation mechanism for sync peers that this method honors
        # once the sync group management is actually handled by the peers via
        # messages.
        max_rep = max((g[querying_peer_id].reputation
                      for g in self.peer.peer_query_groups(querying_peer_id)),
                      default=0)
        # TODO Unhardcode
        return min(max(10 - max_rep, 0), 10)

    def expect_delay(self, peer_to_query_id):
        """Predict the penalty delay that will be imposed."""
        # TODO Handle the case where peer_to_query is a sync_peer. See comment
        # in decide_delay().
        max_rep = max((g[self.peer.peer_id].reputation
                       for g in self.peer.peer_query_groups(peer_to_query_id)),
                      default=0)
        # TODO Unhardcode
        return min(max(10 - max_rep, 0), 10)


class Peer:
    ID_LENGTH = 16
    PREFIX_LENGTH = 4
    MIN_DESIRED_QUERY_PEERS = 2
    MAX_DESIRED_GROUP_SIZE = 16
    QUERY_TIMEOUT = 2
    COMPLETED_QUERY_RETENTION_TIME = 100
    UPDATE_RETENTION_TIME = 100

    def __init__(self, env, logger, network, peer_id, all_query_groups):
        self.env = env
        self.logger = logger
        self.network = network
        self.peer_id = peer_id
        self.all_query_groups = all_query_groups
        self.prefix = self.peer_id[:Peer.PREFIX_LENGTH]
        self.query_groups = OrderedDict()
        self.sync_peers = OrderedDict()
        self.pending_queries = OrderedDict()
        self.completed_queries = OrderedDict()
        self.address = self.network.register(self)
        self.behavior = PeerBehavior(self)

        # Add self-loop to the peer graph so that networkx considers the node
        # for this peer a component.
        self.logger.log(an.ConnectionAdd(self.env.now, self.peer_id,
                                         self.peer_id, None))

    def __lt__(self, other):
        return self.peer_id < other.peer_id

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
            qg[peer.peer_id] = QueryPeerInfo(peer.peer_id, peer.prefix,
                                             peer.address)

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
                        and len(query_group) < Peer.MAX_DESIRED_GROUP_SIZE
                        and self.peer_id not in query_group):
                    self.add_to_query_group(query_group, self)
                    query_group_copy = deepcopy(query_group)
                    query_group_copy[self.peer_id] = QueryPeerInfo(
                        self.peer_id, self.prefix, self.address)
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
                if (len(query_group) < Peer.MAX_DESIRED_GROUP_SIZE
                        and peer_info.peer_id not in query_group):
                    self.add_to_query_group(query_group, peer)
                    query_group[peer_info.peer_id] = (
                        QueryPeerInfo(peer_info.peer_id, peer_info.prefix,
                                      peer_info.address))
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
            query_group = QueryGroup(next(query_group_id_iter), (
                (self.peer_id, self.prefix, self.address),
                (peer_info.peer_id, peer_info.prefix, peer_info.address)
            ))
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

    def uncovered_subprefixes(self):
        """Return subprefixes for which no peer is known."""
        return (sp for sp, c in self.subprefixes().items() if c == 0)

    def find_missing_query_peers(self):
        """
        Find peers to cover prefixes for which there are no known peers.

        It's not enough in this case to simply query for a prefix, because
        there may not be any known peer closer to it. Instead, all peers are
        queried by calling on_query() directly with query_all set to True.
        This way, sync peers will be queried as well.
        """
        for subprefix in self.uncovered_subprefixes():
            self.behavior.on_query(self.peer_id, subprefix, True)

    def introduce(self, peer_info):
        """
        Introduce another peer to this peer.

        If the peer is already known, the address is updated.

        This peer will be able to directly contact the other peer without
        needing to look up the ID/address mapping.
        """
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
            for sp, count in self.subprefixes().items():
                if (peer_info.prefix.startswith(sp)
                        and count < Peer.MIN_DESIRED_QUERY_PEERS):
                    self.join_group_with(peer_info)
                    self.logger.log(an.ConnectionAdd(self.env.now,
                                                     self.peer_id,
                                                     peer_info.peer_id, None))

    def subprefixes(self):
        """
        Map each subprefix to the number of known peers serving it.

        A subprefix is a k-bit bitstring with k > 0, k <= len(self.prefix), in
        which the first k-1 bits are equal to the first k-1 bits in
        self.prefix, and the k-th bit is inverted.

        The dictionary that is returned maps each of the possible
        len(self.prefix) such subprefixes to the number of peers this peer
        knows who can serve it.
        """
        # TODO Cache.
        subprefixes = OrderedDict()
        for i in range(len(self.prefix)):
            subprefixes[self.prefix[:i] + ~(self.prefix[i:i+1])]\
                = SortedIterSet()
        for query_peer_info in self.known_query_peers():
            for sp in subprefixes.keys():
                if query_peer_info.prefix.startswith(sp):
                    subprefixes[sp].add(query_peer_info.peer_id)
        return OrderedDict((sp, len(qps)) for (sp, qps) in subprefixes.items())

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
        if queried_peer_info is None:
            queried_peer_id = None
        else:
            queried_peer_id = queried_peer_info.peer_id
        in_event_id = self.logger.log(
            an.ResponseSent(self.env.now,
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
        for queried_id in queried_ids:
            pending_query = self.pending_queries.get(queried_id)
            if pending_query is not None:
                break
        for qid in queried_ids:
            # Only one of the queried IDs for which we receive a response
            # should have a pending query on record (namely the longest one).
            # The other IDs should be part of that record, but not the key for
            # it.
            assert qid == queried_id or qid not in self.pending_queries
        if pending_query is None:
            status = self.check_completed_queries(responding_peer_id,
                                                  queried_id,
                                                  queried_peer_info)
            if status is None:
                status = 'unmatched'
            in_event_id = self.logger.log(event(status))
            return
        if responding_peer_id not in pending_query.queries_sent:
            status = self.check_completed_queries(responding_peer_id,
                                                  queried_id,
                                                  queried_peer_info)
            if status is None:
                status = 'wrong_responder'
            in_event_id = self.logger.log(event(status))
            return
        pending_query.timeout_proc.interrupt()
        if queried_peer_info is not None:
            in_event_id = self.logger.log(event('success'))
            self.behavior.on_response_success(pending_query,
                                              responding_peer_id,
                                              queried_peer_info, in_event_id)
            self.pending_queries.pop(queried_id, None)
            self.archive_completed_query(pending_query, queried_id)
            self.introduce(queried_peer_info)
            return
        if len(pending_query.peers_to_query) == 0:
            in_event_id = self.logger.log(event('failure_ultimate'))
            self.behavior.on_response_failure(pending_query,
                                              responding_peer_id, in_event_id)
            self.pending_queries.pop(queried_id, None)
            self.archive_completed_query(pending_query, queried_id)
            return
        in_event_id = self.logger.log(event('failure_retry'))
        self.behavior.on_response_retry(pending_query, responding_peer_id,
                                        queried_id, in_event_id)

    def send_reputation_update(self, peer_id, reputation_diff, in_event_id):
        """
        :param reputation_diff: The reputation increase that should be applied.
            Negative values mean a penalty.
        """
        # TODO Also send when the update is meant to be applied (the current
        # time). If there are multiple updates, order may matter if one
        # subtracts and one adds. Receivers need to maintain a recent history
        # in order to roll back and reapply in the correct order.
        query_groups = list(self.peer_query_groups(peer_id))
        query_group_ids = SortedIterSet(qg.query_group_id
                                        for qg in query_groups)
        query_peer_ids = SortedIterSet(pi for qg in query_groups for pi in qg)
        self.logger.log(an.ReputationUpdate(self.env.now, peer_id,
                                            reputation_diff, query_group_ids,
                                            in_event_id))

        # TODO This is just a temporary solution since query group objects are
        # shared between peers (so there must be only one change to the
        # reputation variable). Do this on receipt of an update once every
        # peer maintains its own query group objects.
        for query_group in query_groups:
            new_rep = max(0, query_group[peer_id].reputation + reputation_diff)
            query_group[peer_id].reputation = new_rep

        for query_peer_id in query_peer_ids:
            in_event_id = self.logger.log(
                an.ReputationUpdateSent(self.env.now, self.peer_id,
                                        query_peer_id, peer_id,
                                        reputation_diff, query_group_ids,
                                        in_event_id))
            address = self.lookup_address_local(query_peer_id)
            self.network.send_reputation_update(self.peer_id, self.address,
                                                address, peer_id,
                                                reputation_diff, self.env.now,
                                                in_event_id)

    def recv_reputation_update(self, sender_id, peer_id, reputation_diff, time,
                               in_event_id):
        """
        :param time: The time at which the update is meant to be applied.
        """
        # TODO Ignore updates from peers about themselves.
        self.logger.log(an.ReputationUpdateReceived(
            self.env.now, sender_id, self.peer_id, peer_id, reputation_diff,
            in_event_id))
        # Only change the reputation in those query groups shared by the peer
        # whose reputation is changed and the peer reporting the change.
        # In the other groups there will be peers that don't know about the
        # update.
        query_groups = SortedIterSet(g for g in self.peer_query_groups(peer_id)
                                     if sender_id in g)
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
            new_rep = max(0, query_peer_info.reputation + reputation_diff)
            # Reapply rolled back updates.
            for update in younger_updates:
                new_rep = max(0, new_rep + update.reputation_diff)
                query_peer_info.reputation_updates.append(update)
            query_peer_info.reputation = new_rep
            # Prune old updates. This must not be done too eagerly, as it could
            # otherwise result in desynchronization of the reputation record
            # between peers.
            del_idx = next((i + 1 for (i, update)
                            in enumerate(query_peer_info.reputation_updates)
                            if update.time < self.env.now
                            - Peer.UPDATE_RETENTION_TIME), 0)
            del query_peer_info.reputation_updates[:del_idx]

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
                # TODO Using None as in_event_id because we're not storing the
                # ID of the event leading to this.
                self.behavior.do_rep_success(responding_peer_id, None)
            else:
                status = 'late_failure'
                # TODO Using None as in_event_id because we're not storing the
                # ID of the event leading to this.
                self.behavior.do_rep_failure(responding_peer_id, None)
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
        util.do_delayed(self.env, Peer.COMPLETED_QUERY_RETENTION_TIME,
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
        timeout = (Peer.QUERY_TIMEOUT
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
        if len(pending_query.peers_to_query) == 0:
            in_event_id = self.logger.log(event('failure_ultimate'))
            self.behavior.on_timeout_failure(pending_query, recipient_id,
                                             in_event_id)
            self.pending_queries.pop(queried_id, None)
            self.archive_completed_query(pending_query, queried_id)
            return
        in_event_id = self.logger.log(event('failure_retry'))
        self.behavior.on_timeout_retry(pending_query, recipient_id,
                                       queried_id, in_event_id)

    def peer_query_groups(self, peer_id):
        """Iterate query groups that contain a peer."""
        # TODO Maintain a map of all peers so we don't have to iterate over all
        # groups.
        return (g for g in self.query_groups.values()
                if peer_id in g.members())

    def known_query_peers(self):
        """
        Iterate known query peers.

        The generated elements are QueryPeerInfo objects.

        Not guaranteed to be unique, will contain peers multiple times if they
        share multiple query groups.
        """
        return (pi for g in self.query_groups.values() for pi in g.infos())

    # TODO Should this be part of the behavior?
    def select_peers_to_query(self, queried_id):
        """
        List peers to send a query to.

        Creates a list containing all peers that should be queried for the
        given ID. These are all known peers who are closer to that ID, i.e.
        whose bit_overlap() is larger than for this peer.

        The list is sorted by the overlap, with the largest, i.e. the closest
        to the ID (and thus most useful) first.
        """
        own_overlap = util.bit_overlap(self.prefix, queried_id)
        peers_to_query_info = []
        for query_peer_info in SortedIterSet(self.known_query_peers()):
            # TODO Range queries for performance.
            if (util.bit_overlap(query_peer_info.prefix, queried_id)
                    > own_overlap):
                peers_to_query_info.append(query_peer_info)
        # TODO Instead of sorting for the longest prefix match, use a heap to
        # begin with.
        # TODO Also consider reputation in the query group when selecting a
        # peer to query.
        peers_to_query_info.sort(key=lambda pi: util.bit_overlap(pi.prefix,
                                                                 queried_id),
                                 reverse=True)
        return [pi.peer_id for pi in peers_to_query_info]


class QueryGroup:
    def __init__(self, query_group_id, members):
        """
        Create a query group with some initial members.
        :param members: An iterable of 3-tuples containing peer ID, prefix and
            address.
        """
        self.query_group_id = query_group_id
        self._members = OrderedDict((peer_id,
                                     QueryPeerInfo(peer_id, prefix, address))
                                    for (peer_id, prefix, address) in members)

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
    def __init__(self, peer_id, prefix, address):
        super().__init__(peer_id, prefix, address)
        self.reputation = 0
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
