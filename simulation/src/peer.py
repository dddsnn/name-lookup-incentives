import analyze as an
import util
from simulation import (SUCCESSFUL_QUERY_REWARD, FAILED_QUERY_PENALTY,
                        TIMEOUT_QUERY_PENALTY)
import simpy


class PeerBehavior:
    def __init__(self, peer):
        self.peer = peer

    def act_query_self(self, querying_peer_id, queried_id, in_event_id):
        min_rep = min((g[self.peer.peer_id].reputation for g in
                       self.peer.peer_query_groups(querying_peer_id)),
                      default=0)
        # TODO Unhardcode
        if querying_peer_id == self.peer.peer_id or min_rep < 15:
            self.act_query_self_default(querying_peer_id, queried_id,
                                        in_event_id)

    def act_query_sync(self, querying_peer_id, queried_id, sync_peer_info,
                       in_event_id):
        min_rep = min((g[self.peer.peer_id].reputation for g in
                       self.peer.peer_query_groups(querying_peer_id)),
                      default=0)
        # TODO Unhardcode
        if querying_peer_id == self.peer.peer_id or min_rep < 15:
            self.act_query_sync_default(querying_peer_id, queried_id,
                                        sync_peer_info, in_event_id)

    def act_query(self, querying_peer_id, queried_id, in_event_id,
                  query_all=False):
        min_rep = min((g[self.peer.peer_id].reputation for g in
                       self.peer.peer_query_groups(querying_peer_id)),
                      default=0)
        # TODO Unhardcode
        if querying_peer_id == self.peer.peer_id or min_rep < 15:
            self.act_query_default(querying_peer_id, queried_id, in_event_id,
                                   query_all)

    def act_response_success(self, pending_query, responding_peer_id,
                             queried_id, queried_peer_info, time_taken,
                             in_event_id):
        self.act_response_success_default(pending_query, responding_peer_id,
                                          queried_id, queried_peer_info,
                                          time_taken, in_event_id)

    def act_response_failure(self, pending_query, responding_peer_id,
                             queried_id, time_taken, in_event_id):
        self.act_response_failure_default(pending_query, responding_peer_id,
                                          queried_id, time_taken, in_event_id)

    def act_response_retry(self, pending_query, responding_peer_id, queried_id,
                           in_event_id):
        self.act_response_retry_default(pending_query, responding_peer_id,
                                        queried_id, in_event_id)

    def act_timeout_failure(self, pending_query, recipient_id, queried_id,
                            in_event_id):
        self.act_timeout_failure_default(pending_query, recipient_id,
                                         queried_id, in_event_id)

    def act_timeout_retry(self, pending_query, recipient_id, queried_id,
                          in_event_id):
        self.act_timeout_retry_default(pending_query, recipient_id, queried_id,
                                       in_event_id)

    def act_rep_success(self, peer_id):
        self.act_rep_success_default(peer_id)

    def act_rep_failure(self, peer_id):
        self.act_rep_failure_default(peer_id)

    def act_rep_timeout(self, peer_id):
        self.act_rep_timeout_default(peer_id)

    def act_decide_delay(self, querying_peer_id):
        return self.act_decide_delay_default(querying_peer_id)

    def act_expect_delay(self, peer_to_query_id):
        return self.act_expect_delay_default(peer_to_query_id)

    def act_query_self_default(self, querying_peer_id, queried_id,
                               in_event_id):
        delay = self.act_decide_delay(querying_peer_id)
        info = PeerInfo(self.peer.peer_id, self.peer.prefix, self.peer.address)
        self.peer.send_response(querying_peer_id, set((queried_id,)), info,
                                in_event_id, delay=delay)

    def act_query_sync_default(self, querying_peer_id, queried_id,
                               sync_peer_info, in_event_id):
        delay = self.act_decide_delay(querying_peer_id)
        self.peer.send_response(querying_peer_id, set((queried_id,)),
                                sync_peer_info, in_event_id, delay=delay)

    def act_query_default(self, querying_peer_id, queried_id, in_event_id,
                          query_all=False):
        """
        Act when a query is necessary.

        This method implements the "good" default behavior. A list of peers is
        created that will be queried and sorted based on how close they are to
        the queried ID. A PendingQuery is created with these peers and used to
        send a query.

        By default, the peers that will be queried are only ones whose prefix
        has a larger overlap with the queried ID than this peer, i.e. who are
        closer to the target ID. However, if query_all is True, all known
        peers, including sync peers, will be queried.
        """
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
            print(('{:.2f}: {}: query for {} impossible, no known peer closer'
                   ' to it')
                  .format(self.peer.env.now, self.peer.peer_id, queried_id))
            return
        pending_query = PendingQuery(self.peer.env.now, querying_peer_id,
                                     queried_id, peers_to_query)
        self.peer.pending_queries[queried_id] = pending_query
        self.peer.send_query(queried_id, pending_query, in_event_id)
        # TODO Send queries to multiple peers at once.

    def act_response_success_default(self, pending_query, responding_peer_id,
                                     queried_id, queried_peer_info, time_taken,
                                     in_event_id):
        queried_ids = pending_query.querying_peers.pop(self.peer.peer_id, None)
        total_time = self.peer.env.now - pending_query.start_time
        if queried_ids is not None:
            # TODO Update the ID/address mapping, even if we're just passing
            # the query result through to another peer.
            print(('{:.2f}: {}: successful response for query for {} from'
                   ' {} after {:.2f}, total time {:.2f}')
                  .format(self.peer.env.now, self.peer.peer_id,
                          util.format_ids(queried_id, queried_ids),
                          responding_peer_id, time_taken, total_time))
        for querying_peer_id, queried_ids in (pending_query.querying_peers
                                              .items()):
            delay = max(self.act_decide_delay(querying_peer_id)
                        - total_time, 0)
            self.peer.send_response(querying_peer_id, queried_ids,
                                    queried_peer_info, in_event_id,
                                    delay=delay)
        self.act_rep_success(responding_peer_id)

    def act_response_failure_default(self, pending_query, responding_peer_id,
                                     queried_id, time_taken, in_event_id):
        queried_ids = pending_query.querying_peers.get(self.peer.peer_id)
        total_time = self.peer.env.now - pending_query.start_time
        if queried_ids is not None:
            print(('{:.2f}: {}: unsuccessful query for {} last sent to {}:'
                   ' unsuccessful response from last known peer after {:.2f},'
                   ' total time {:.2f}')
                  .format(self.peer.env.now, self.peer.peer_id,
                          util.format_ids(queried_id, queried_ids),
                          responding_peer_id, time_taken, total_time))
        for querying_peer_id, queried_ids in (pending_query.querying_peers
                                              .items()):
            delay = max(self.act_decide_delay(querying_peer_id)
                        - total_time, 0)
            self.peer.send_response(querying_peer_id, queried_ids, None,
                                    in_event_id, delay=delay)
        self.act_rep_failure(responding_peer_id)

    def act_response_retry_default(self, pending_query, responding_peer_id,
                                   queried_id, in_event_id):
        queried_ids = pending_query.querying_peers.get(self.peer.peer_id)
        if queried_ids is not None:
            print(('{:.2f}: {}: unsuccessful response for query for {} from'
                   ' {}, trying next peer')
                  .format(self.peer.env.now, self.peer.peer_id,
                          util.format_ids(queried_id, queried_ids),
                          responding_peer_id))
        self.peer.send_query(queried_id, pending_query, in_event_id)
        self.act_rep_failure(responding_peer_id)

    def act_timeout_failure_default(self, pending_query, recipient_id,
                                    queried_id, in_event_id):
        queried_ids = pending_query.querying_peers.get(self.peer.peer_id)
        total_time = self.peer.env.now - pending_query.start_time
        if queried_ids is not None:
            queried_ids = pending_query.querying_peers[self.peer.peer_id]
            print(('{:.2f}: {}: unsuccessful query for {} last sent to {}:'
                   ' last known peer timed out, total time {:.2f}')
                  .format(self.peer.env.now, self.peer.peer_id,
                          util.format_ids(queried_id, queried_ids),
                          recipient_id, total_time))
        for querying_peer_id, queried_ids in (pending_query.querying_peers
                                              .items()):
            delay = max(self.act_decide_delay(querying_peer_id)
                        - total_time, 0)
            self.peer.send_response(querying_peer_id, queried_ids, None,
                                    in_event_id, delay=delay)
        self.act_rep_timeout(recipient_id)

    def act_timeout_retry_default(self, pending_query, recipient_id,
                                  queried_id, in_event_id):
        queried_ids = pending_query.querying_peers.get(self.peer.peer_id)
        if queried_ids is not None:
            queried_ids = pending_query.querying_peers[self.peer.peer_id]
            print('{:.2f}: {}: timed out response for query for {} sent to {},'
                  ' trying next peer'
                  .format(self.peer.env.now, self.peer.peer_id,
                          util.format_ids(queried_id, queried_ids),
                          recipient_id))
        self.peer.send_query(queried_id, pending_query, in_event_id)
        self.act_rep_timeout(recipient_id)

    def act_rep_success_default(self, peer_id):
        for query_group in self.peer.peer_query_groups(peer_id):
            rep = max(query_group[peer_id].reputation
                      + SUCCESSFUL_QUERY_REWARD, 0)
            query_group[peer_id].reputation = rep

    def act_rep_failure_default(self, peer_id):
        for query_group in self.peer.peer_query_groups(peer_id):
            rep = max(query_group[peer_id].reputation
                      + FAILED_QUERY_PENALTY, 0)
            query_group[peer_id].reputation = rep

    def act_rep_timeout_default(self, peer_id):
        for query_group in self.peer.peer_query_groups(peer_id):
            rep = max(query_group[peer_id].reputation
                      + TIMEOUT_QUERY_PENALTY, 0)
            query_group[peer_id].reputation = rep

    def act_decide_delay_default(self, querying_peer_id):
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

    def act_expect_delay_default(self, peer_to_query_id):
        # TODO Handle the case where peer_to_query is a sync_peer. See comment
        # in act_decide_delay_default().
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

    def __init__(self, env, logger, network, peer_id, all_query_groups,
                 peer_graph):
        self.env = env
        self.logger = logger
        self.network = network
        self.peer_id = peer_id
        self.all_query_groups = all_query_groups
        self.peer_graph = peer_graph
        self.prefix = self.peer_id[:Peer.PREFIX_LENGTH]
        self.query_groups = set()
        self.sync_peers = {}
        self.pending_queries = {}
        self.completed_queries = {}
        self.address = self.network.register(self)
        self.behavior = PeerBehavior(self)

        # Add self-loop to the peer graph so that networkx considers the node
        # for this peer a component.
        self.peer_graph.add_edge(self.peer_id, self.peer_id)

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
        for query_group in self.query_groups:
            peer_info = query_group.get(peer_id)
            if peer_info is None:
                continue
            return peer_info.address
        return None

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
        # TODO Instead of just adding self or others to groups, send join
        # requests or invites.
        # Attempt to join one of the peer's groups.
        # TODO Don't use the global information all_query_groups.
        for query_group in self.all_query_groups:
            # TODO Pick the most useful out of these groups, not just any.
            if (peer_info.peer_id in query_group
                    and len(query_group) < Peer.MAX_DESIRED_GROUP_SIZE
                    and self.peer_id not in query_group):
                query_group[self.peer_id] = QueryPeerInfo(self.peer_id,
                                                          self.prefix,
                                                          self.address)
                self.query_groups.add(query_group)
                return
        # Attempt to add the peer to one of my groups.
        for query_group in self.query_groups:
            # TODO Pick the most useful out of these groups, not just any.
            if (len(query_group) < Peer.MAX_DESIRED_GROUP_SIZE
                    and peer_info.peer_id not in query_group):
                query_group[peer_info.peer_id] = (
                    QueryPeerInfo(peer_info.peer_id, peer_info.prefix,
                                  peer_info.address))
                # TODO Remove this hack. We need to add the new query group to
                # the other peer's set of query groups. But the only place
                # storing the peer references is the network, so we have to
                # abuse its private peer map. Remove this once query group
                # invites are implemented.
                peer = self.network.peers[peer_info.address]
                assert peer.peer_id == peer_info.peer_id
                peer.query_groups.add(query_group)
                return
        # Create a new query group.
        query_group = QueryGroup({
            self.peer_id: (self.prefix, self.address),
            peer_info.peer_id: (peer_info.prefix, peer_info.address)
        })
        self.all_query_groups.add(query_group)
        self.query_groups.add(query_group)
        # TODO Remove this hack. We need to add the new query group to the
        # other peer's set of query groups. But the only place storing the peer
        # references is the network, so we have to abuse its private peer map.
        # Remove this once query group invites are implemented.
        peer = self.network.peers[peer_info.address]
        assert peer.peer_id == peer_info.peer_id
        peer.query_groups.add(query_group)

    def find_missing_query_peers(self):
        """
        Find peers to cover prefixes for which there are no known peers.

        It's not enough in this case to simply query for a prefix, because
        there may not be any known peer closer to it. Instead, all peers are
        queried by calling act_query() directly with query_all set to True.
        This way, sync peers will be queried as well.
        """
        for subprefix in (sp for sp, c in self.subprefixes().items()
                          if c == 0):
            self.behavior.act_query(self.peer_id, subprefix, True)

    def introduce(self, peer_info):
        """
        Introduce another peer to this peer.

        If the peer is already known, the address is updated.

        This peer will be able to directly contact the other peer without
        needing to look up the ID/address mapping.
        """
        if peer_info.peer_id.startswith(self.prefix):
            self.sync_peers[peer_info.peer_id] = peer_info
            self.peer_graph.add_edge(self.peer_id, peer_info.peer_id)
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
                    self.peer_graph.add_edge(self.peer_id, peer_info.peer_id)

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
        subprefixes = {}
        for i in range(len(self.prefix)):
            subprefixes[self.prefix[:i] + ~(self.prefix[i:i+1])] = set()
        for query_peer_info in self.known_query_peers():
            for sp in subprefixes.keys():
                if query_peer_info.prefix.startswith(sp):
                    subprefixes[sp].add(query_peer_info.peer_id)
        return {sp: len(qps) for (sp, qps) in subprefixes.items()}

    def handle_request(self, queried_id):
        print('{:.2f}: {}: request for {} - '.format(self.env.now,
                                                     self.peer_id,
                                                     queried_id), end='')
        try:
            for pending_queried_id in self.pending_queries:
                if pending_queried_id.startswith(queried_id):
                    status = 'pending'
                    print('request for matching ID {} is already pending'
                          .format(pending_queried_id))
                    return
            if queried_id == self.peer_id:
                status = 'own_id'
                print('request for own ID')
                return
            for sync_peer_id in self.sync_peers:
                if sync_peer_id.startswith(queried_id):
                    # TODO Actually send query in case queried_id is a prefix.
                    # This behavior is useless for the purpose of finding more
                    # sync peers.
                    status = 'known'
                    print('found matching ID {} in sync peers'
                          .format(sync_peer_id))
                    return
            print('sending query')
            status = 'querying'
        finally:
            in_event_id = self.logger.log(an.Request(self.env.now,
                                                     self.peer_id,
                                                     queried_id, status))
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
            self.behavior.act_query_self(querying_peer_id, queried_id,
                                         in_event_id)
            return
        for sync_peer_id, sync_peer_info in self.sync_peers.items():
            if sync_peer_id.startswith(queried_id):
                if not skip_log:
                    in_event_id = self.logger.log(event('known'))
                self.behavior.act_query_sync(querying_peer_id, queried_id,
                                             sync_peer_info, in_event_id)
                return
        for pending_query_id, pending_query in self.pending_queries.items():
            if pending_query_id.startswith(queried_id):
                if not skip_log:
                    in_event_id = self.logger.log(event('pending'))
                # There already is a query for a fitting ID in progress, just
                # note to also send a response to this querying peer.
                pending_query.querying_peers.setdefault(querying_peer_id,
                                                        set()).add(queried_id)
                return
        if not skip_log:
            in_event_id = self.logger.log(event('querying'))
        self.behavior.act_query(querying_peer_id, queried_id, in_event_id)

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
        time_sent = pending_query.queries_sent.pop(responding_peer_id)
        time_taken = self.env.now - time_sent
        if queried_peer_info is not None:
            in_event_id = self.logger.log(event('success'))
            self.behavior.act_response_success(pending_query,
                                               responding_peer_id, queried_id,
                                               queried_peer_info, time_taken,
                                               in_event_id)
            self.pending_queries.pop(queried_id, None)
            self.archive_completed_query(pending_query, queried_id)
            self.introduce(queried_peer_info)
            return
        if len(pending_query.peers_to_query) == 0:
            in_event_id = self.logger.log(event('failure_ultimate'))
            self.behavior.act_response_failure(pending_query,
                                               responding_peer_id, queried_id,
                                               time_taken, in_event_id)
            self.pending_queries.pop(queried_id, None)
            self.archive_completed_query(pending_query, queried_id)
            return
        in_event_id = self.logger.log(event('failure_retry'))
        self.behavior.act_response_retry(pending_query, responding_peer_id,
                                         queried_id, in_event_id)

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
                self.behavior.act_rep_success(responding_peer_id)
            else:
                status = 'late_failure'
                self.behavior.act_rep_failure(responding_peer_id)
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
                   + self.behavior.act_expect_delay(recipient_id))
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
            self.behavior.act_timeout_failure(pending_query, recipient_id,
                                              queried_id, in_event_id)
            self.pending_queries.pop(queried_id, None)
            self.archive_completed_query(pending_query, queried_id)
            return
        in_event_id = self.logger.log(event('failure_retry'))
        self.behavior.act_timeout_retry(pending_query, recipient_id,
                                        queried_id, in_event_id)

    def peer_query_groups(self, peer_id):
        """Iterate query groups that contain a peer."""
        # TODO Maintain a map of all peers so we don't have to iterate over all
        # groups.
        return (g for g in self.query_groups if peer_id in g.members())

    def known_query_peers(self):
        """
        Iterate known query peers.

        The generated elements are QueryPeerInfo objects.

        Not guaranteed to be unique, will contain peers multiple times if they
        share multiple query groups.
        """
        return (pi for g in self.query_groups for pi in g.infos())

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
        for query_peer_info in set(self.known_query_peers()):
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
    def __init__(self, members):
        """
        Create a query group with some initial members.
        :param members: A dictionary mapping peer IDs to a tuple of prefix and
            address.
        """
        self._members = {peer_id: QueryPeerInfo(peer_id, prefix, address)
                         for peer_id, (prefix, address) in members.items()}

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


class QueryPeerInfo(PeerInfo):
    def __init__(self, peer_id, prefix, address):
        super().__init__(peer_id, prefix, address)
        self.reputation = 0


class PendingQuery:
    def __init__(self, start_time, querying_peer_id, queried_id,
                 peers_to_query, timeout_proc=None):
        self.start_time = start_time
        self.querying_peers = {querying_peer_id: set((queried_id,))}
        self.timeout_proc = timeout_proc
        self.peers_to_query = peers_to_query
        self.queries_sent = {}
