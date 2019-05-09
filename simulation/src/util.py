import simpy
import itertools as it
import collections as cl
import pytrie
import bitstring


class Network:
    def __init__(self, env, settings):
        self.env = env
        self.settings = settings
        self.peers = cl.OrderedDict()
        self.address_iter = it.count()

    def register(self, peer):
        # TODO Reuse addresses.
        address = next(self.address_iter)
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
            delay += self.settings['transmission_delay']
        recipient = self.peers.get(recipient_address)
        if recipient is None:
            raise UnassignedAddressError
        self.env.schedule(event_factory(sender_id, recipient), delay=delay)

    def send_query(self, sender_id, sender_address, recipient_address,
                   queried_id, excluded_peer_ids, in_event_id):
        self.send(sender_id, sender_address, recipient_address,
                  lambda si, r: SendQuery(self.env, si, r, queried_id,
                                          excluded_peer_ids, in_event_id))

    def send_response(self, sender_id, sender_address, recipient_address,
                      queried_id, queried_peer_info, in_event_id):
        self.send(sender_id, sender_address, recipient_address,
                  lambda si, r: SendResponse(self.env, si, r, queried_id,
                                             queried_peer_info, in_event_id))

    def send_reputation_update(self, sender_id, sender_address,
                               recipient_address, peer_id, query_group_ids,
                               reputation_diff, time, in_event_id):
        self.send(sender_id, sender_address, recipient_address,
                  lambda si, r: SendReputationUpdate(
                      self.env, si, r, peer_id, query_group_ids,
                      reputation_diff, time, in_event_id))


class SendQuery(simpy.events.Event):
    def __init__(self, env, sender_id, recipient, queried_id,
                 excluded_peer_ids, in_event_id):
        super().__init__(env)
        self.ok = True
        self.sender_id = sender_id
        self.recipient = recipient
        self.queried_id = queried_id
        self.excluded_peer_ids = excluded_peer_ids
        self.in_event_id = in_event_id
        self.callbacks.append(SendQuery.action)

    def action(self):
        self.recipient.recv_query(self.sender_id, self.queried_id,
                                  self.in_event_id,
                                  excluded_peer_ids=self.excluded_peer_ids)


class SendResponse(simpy.events.Event):
    def __init__(self, env, sender_id, recipient, queried_id,
                 queried_peer_info, in_event_id):
        super().__init__(env)
        self.ok = True
        self.sender_id = sender_id
        self.recipient = recipient
        self.queried_id = queried_id
        self.queried_peer_info = queried_peer_info
        self.in_event_id = in_event_id
        self.callbacks.append(SendResponse.action)

    def action(self):
        self.recipient.recv_response(self.sender_id, self.queried_id,
                                     self.queried_peer_info, self.in_event_id)


class SendReputationUpdate(simpy.events.Event):
    def __init__(self, env, sender_id, recipient, peer_id, query_group_ids,
                 reputation_diff, time, in_event_id):
        super().__init__(env)
        self.ok = True
        self.sender_id = sender_id
        self.recipient = recipient
        self.peer_id = peer_id
        self.query_group_ids = query_group_ids
        self.reputation_diff = reputation_diff
        self.time = time
        self.in_event_id = in_event_id
        self.callbacks.append(SendReputationUpdate.action)

    def action(self):
        self.recipient.recv_reputation_update(
            self.sender_id, self.peer_id, self.query_group_ids,
            self.reputation_diff, self.time, self.in_event_id)


class UnassignedAddressError(Exception):
    pass


class SortedIterSet(set):
    """A set whose iterator returns the elements sorted."""
    def __init__(self, *args):
        super().__init__(*args)

    def __iter__(self):
        li = list(super().__iter__())
        return iter(sorted(li))


class SortedBitsTrie(pytrie.SortedTrie):
    KeyFactory = bitstring.Bits

    def has_prefix_of(self, bits):
        """
        Return whether there is a key that is a prefix of bits.

        This is true if there exists a key k in this trie with
        bits.startswith(k). That implies len(bits) >= len(k).
        """
        try:
            next(self.iter_prefixes(bits))
            return True
        except StopIteration:
            return False

    def is_key_prefix_subset(self, other):
        """
        Return whether each key has a prefix in the other trie.

        This is the case if for each key k1 in this trie there exists a key k2
        in the other such that k1.startswith(k2). That implies
        len(k1) >= len(k2).
        """
        for key in self.iterkeys():
            if not other.has_prefix_of(key):
                return False
        return True


def bit_overlap(a, b):
    """Calculate the number of bits at the start that are the same."""
    m = min(len(a), len(b))
    return len(next((a[:m] ^ b[:m]).split('0b1', count=1)))


def do_delayed(env, delay, function, *args):
    """
    Do something with a delay.

    Creates a process that calls function with args after delay.
    """
    def gen():
        yield env.timeout(delay)
        function(*args)
    env.process(gen())


def do_repeatedly(env, interval, function, *args):
    def gen():
        while True:
            yield env.timeout(interval)
            function(*args)
    env.process(gen())


def progress_process(env, step):
    while True:
        print('\rcurrent time: {}'.format(env.now), end='')
        yield env.timeout(step)


def bits_lt(b1, b2):
    """__lt__ for the bitstrings."""
    return 2 ** len(b1) + b1.uint < 2 ** len(b2) + b2.uint


def read_settings(file_name):
    with open(file_name, 'r') as file:
        settings_str = file.read()
    return eval(settings_str)


class EmptyClass:
    pass


def generic_repr(self):
    excluded = set(EmptyClass.__dict__.keys())
    attrs = ((attr, value) for (attr, value)
             in sorted(self.__dict__.items()) if attr not in excluded)
    return '{}: {{{}}}'.format(type(self).__name__, ', '.join(
        '{}: {}'.format(attr, value) for (attr, value) in attrs))
