import networkx as nx


def print_info_process(env, peers, sync_groups, all_query_groups, peer_graph):
    while True:
        yield env.timeout(10)
        print_info(peers, sync_groups, all_query_groups, peer_graph)


def print_info(peers, sync_groups, all_query_groups, peer_graph):
    print()
    print('sync groups (prefix: {peers}):')
    for pr, sg in sorted(sync_groups.items(), key=lambda t: t[0].uint):
        print('{}: {{{}}}'.format(pr.bin,
                                  ', '.join(str(p.peer_id) for p in sg)))
    print()
    print('query_groups (peer: reputation):')
    for query_group in all_query_groups:
        print('{{{}}}'.format(', '.join(
            str(p.peer_id) + ': ' + '{:.1f}'.format(r)
            for p, r in sorted(query_group.items(), key=lambda t: t[1],
                               reverse=True))))
    print()
    print('missing subprefix coverage per peer:')
    any_missing = False
    for peer in sorted(peers.values(), key=lambda p: p.peer_id.uint):
        if any(n == 0 for n in peer.subprefixes().values()):
            any_missing = True
            missing = set(sp for sp, c in peer.subprefixes().items() if c == 0)
            print('{}: missing prefixes {{{}}}'
                  .format(peer.peer_id, ', '.join((i.bin for i in missing))))
    if not any_missing:
        print('none')
    print()
    print('strongly connected components:')
    from networkx import strongly_connected_components as scc
    for i, comp in enumerate((peer_graph.subgraph(c)
                              for c in scc(peer_graph))):
        print('component {}: {} nodes, diameter {}, degree histogram: {}'
              .format(i, nx.number_of_nodes(comp), nx.diameter(comp),
                      nx.degree_histogram(comp)))
    print()
