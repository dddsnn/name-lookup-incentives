import util
from peer import QueryGroup, query_group_id_iter
import os
import bitstring as bs
from copy import deepcopy


bs.Bits.__lt__ = util.bits_lt


class TestHelper:
    def __init__(self):
        file_name = os.path.join(os.getcwd(), '../default.settings')
        self.settings = util.read_settings(file_name)

    def create_query_group(self, all_query_groups, *peers):
        query_group = QueryGroup(next(query_group_id_iter),
                                 (p.info() for p in peers),
                                 self.settings['initial_reputation'])
        all_query_groups[query_group.query_group_id] = query_group
        for peer in peers:
            peer.query_groups[query_group.query_group_id]\
                = deepcopy(query_group)
        return query_group.query_group_id


class PendingQueryMatcher:
    def __init__(self, querying_peer_id, queried_id, peers_to_query):
        self.querying_peer_id = querying_peer_id
        self.queried_id = queried_id
        self.peers_to_query = peers_to_query

    def __eq__(self, other):
        return (len(other.querying_peers) == 1
                and other.querying_peers[self.querying_peer_id]
                == set((self.queried_id,))
                and self.peers_to_query == other.peers_to_query)


def pending_query(querying_peer_id, queried_id, peers_to_query):
    return PendingQueryMatcher(querying_peer_id, queried_id, peers_to_query)
