import simpy
from itertools import count
from collections import OrderedDict
import pytrie
import bitstring


class Network:
    def __init__(self, env, settings):
        self.env = env
        self.settings = settings
        self.peers = OrderedDict()
        self.address_iter = count()

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
                   queried_id, in_event_id):
        self.send(sender_id, sender_address, recipient_address,
                  lambda si, r: SendQuery(self.env, si, r, queried_id,
                                          in_event_id))

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


def remove_duplicates(ls, key=None):
    """
    Removes duplicate entries from a list.

    Removes all but the first occurrence of duplicate entries and leaves the
    order of the list intact.

    If key is None (default), checks for duplicates by comparing the list
    entries themselves, if key is a function, invokes it on each of the list
    entries and compares based on the result.
    """
    items = set()
    i = 0
    while i < len(ls):
        item = ls[i]
        if key:
            item = key(item)
        if item in items:
            ls.pop(i)
        else:
            items.add(item)
            i += 1


class EmptyClass:
    pass


def generic_repr(self):
    excluded = set(EmptyClass.__dict__.keys())
    attrs = ((attr, value) for (attr, value)
             in sorted(self.__dict__.items()) if attr not in excluded)
    return '{}: {{{}}}'.format(type(self).__name__, ', '.join(
        '{}: {}'.format(attr, value) for (attr, value) in attrs))
