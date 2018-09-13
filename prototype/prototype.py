import simpy

class Peer:
    def __init__(self, env):
        self.env = env

        env.process(self.request_generator())

    def request_generator(self):
        while True:
            yield env.timeout(1)
            self.handle_request()

    def handle_request(self):
        print('handling request at {}'.format(env.now))

if __name__ == '__main__':
    env = simpy.Environment()
    Peer(env)
    env.run(until=float('inf'))
