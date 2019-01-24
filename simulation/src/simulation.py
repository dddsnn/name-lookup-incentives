import peer as p
import analyze as an
import simpy
import bitstring as bs
import random
import networkx as nx

SUCCESSFUL_QUERY_REWARD = 1
FAILED_QUERY_PENALTY = -2
TIMEOUT_QUERY_PENALTY = -2
DECAY_TIMESTEP = 1
DECAY_PER_TIME_UNIT = 0.1


class Network:
    TRANSMISSION_DELAY = 0.1

    def __init__(self, env):
        self.env = env
        self.peers = {}
        self.next_address = 0

    def register(self, peer):
        # TODO Reuse addresses.
        address = self.next_address
        self.next_address += 1
        self.peers[address] = peer
        return address

    def send(self, sender_id, sender_address, recipient_address,
             event_factory):
        """
        Send a message by scheduling an event.
        :param event_factory: A function taking a sender ID and a recipient
            (*not* a recipient address) and returning a simPy event to be
            scheduled with an appropriate delay.
        """
        delay = 0
        if sender_address != recipient_address:
            delay += Network.TRANSMISSION_DELAY
        recipient = self.peers.get(recipient_address)
        if recipient is None:
            raise UnassignedAddressError
        self.env.schedule(event_factory(sender_id, recipient), delay=delay)

    def send_query(self, sender_id, sender_address, recipient_address,
                   queried_id, in_event_id):
        self.send(sender_id, sender_address, recipient_address,
                  lambda si, r: SendQuery(self.env, si, r, queried_id,
                                          in_event_id))

    def send_response(self, sender_id, sender_address, recipient_address,
                      queried_ids, queried_peer_info, in_event_id):
        self.send(sender_id, sender_address, recipient_address,
                  lambda si, r: SendResponse(self.env, si, r, queried_ids,
                                             queried_peer_info, in_event_id))


class SendQuery(simpy.events.Event):
    def __init__(self, env, sender_id, recipient, queried_id, in_event_id):
        super().__init__(env)
        self.ok = True
        self.sender_id = sender_id
        self.recipient = recipient
        self.queried_id = queried_id
        self.in_event_id = in_event_id
        self.callbacks.append(SendQuery.action)

    def action(self):
        self.recipient.recv_query(self.sender_id, self.queried_id,
                                  self.in_event_id)


class SendResponse(simpy.events.Event):
    def __init__(self, env, sender_id, recipient, queried_ids,
                 queried_peer_info, in_event_id):
        super().__init__(env)
        self.ok = True
        self.sender_id = sender_id
        self.recipient = recipient
        self.queried_ids = queried_ids
        self.queried_peer_info = queried_peer_info
        self.in_event_id = in_event_id
        self.callbacks.append(SendResponse.action)

    def action(self):
        self.recipient.recv_response(self.sender_id, self.queried_ids,
                                     self.queried_peer_info, self.in_event_id)


class UnassignedAddressError(Exception):
    pass


def bit_overlap(a, b):
    """Calculate the number of bits at the start that are the same."""
    m = min(len(a), len(b))
    return len(next((a[:m] ^ b[:m]).split('0b1', count=1)))


def request_generator(env, peers, peer):
    while True:
        if len(peers) <= 1:
            break
        while True:
            query_peer_id = random.sample(peers.keys(), 1)[0]
            if query_peer_id != peer.peer_id:
                break
        peer.handle_request(query_peer_id)
        yield env.timeout(1)


def decay_reputation(env, all_query_groups):
    while True:
        yield env.timeout(DECAY_TIMESTEP)
        decay = DECAY_PER_TIME_UNIT * DECAY_TIMESTEP
        for query_group in all_query_groups:
            for query_peer_info in query_group.infos():
                query_peer_info.reputation = max(0, query_peer_info.reputation
                                                 - decay)


def do_delayed(env, delay, function, *args):
    """
    Do something with a delay.

    Creates a process that calls function with args after delay.
    """
    def gen():
        yield env.timeout(delay)
        function(*args)
    env.process(gen())


def format_ids(queried_id, queried_ids):
    """Pretty-print an ID and set of prefixes."""
    s = str(queried_id)
    if len(queried_ids) > 1:
        s += ' ({' + ', '.join((str(qid) for qid in queried_ids)) + '})'
    return s


if __name__ == '__main__':
    random.seed(a=0, version=2)
    env = simpy.Environment()
    logger = an.Logger()
    peers = {}
    sync_groups = {}
    all_query_groups = set()
    peer_graph = nx.DiGraph()
    network = Network(env)
    for i in range(64):
        while True:
            peer_id_uint = random.randrange(2 ** p.Peer.ID_LENGTH)
            peer_id = bs.Bits(uint=peer_id_uint, length=p.Peer.ID_LENGTH)
            if peer_id not in peers:
                peer = p.Peer(env, logger, network, peer_id, all_query_groups,
                              peer_graph)
                peers[peer_id] = peer
                sync_groups.setdefault(peer_id[:p.Peer.PREFIX_LENGTH],
                                       set()).add(peer)
                env.process(request_generator(env, peers, peer))
                break
    for sync_group in sync_groups.values():
        for peer in sync_group:
            for other_peer in sync_group:
                peer.introduce(p.PeerInfo(other_peer.peer_id,
                                          other_peer.prefix,
                                          other_peer.address))
    for peer in peers.values():
        for other_peer in random.sample(list(peers.values()), 8):
            peer.introduce(p.PeerInfo(other_peer.peer_id, other_peer.prefix,
                                      other_peer.address))

    an.print_info(peers, sync_groups, all_query_groups, peer_graph)
    env.process(an.print_info_process(env, peers, sync_groups,
                                      all_query_groups,
                                      peer_graph))
    print('scheduling queries for missing subprefixes')
    for peer in peers.values():
        peer.find_missing_query_peers()
    print()
    print('starting simulation')
    env.process(decay_reputation(env, all_query_groups))
    env.run(until=10)
    logger.dump('log')
