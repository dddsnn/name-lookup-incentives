import util
from peer import QueryGroup, query_group_id_iter
import os
import bitstring as bs
from copy import deepcopy


bs.Bits.__lt__ = util.bits_lt


def get_settings():
    file_name = os.path.join(os.getcwd(), '../default.settings')
    return util.read_settings(file_name)


def create_query_group(all_query_groups, *peers):
    query_group = QueryGroup(next(query_group_id_iter),
                             (p.info() for p in peers))
    all_query_groups[query_group.query_group_id] = query_group
    for peer in peers:
        peer.query_groups[query_group.query_group_id] = deepcopy(query_group)
    return query_group.query_group_id
