import os

DEFAULT_PIPE_PATH = "/tmp/iotc-pipe"

class IOTCPipe:
    def __init__(self, pipe_name, read_type):
        self.pipe_name = pipe_name
        if not os.path.exists(self.pipe_name):
            os.mkfifo(self.pipe_name)
        self.pipe = open(self.pipe_name, read_type)

    def send_data(self, data):
        self.pipe.write(data)
        self.pipe.flush()

    def receive_data(self):
        data = self.pipe.readline()
        return data

    def close_connection(self):
        self.pipe.close()

    @classmethod
    def send(cls,data):
        cls.__init__(cls,DEFAULT_PIPE_PATH, 'w')
        cls.send_data(cls,data)
        cls.close_connection(cls)