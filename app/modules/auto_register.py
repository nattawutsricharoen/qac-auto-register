"""Auto Register module state; scanned document metadata belongs here."""
class AutoRegisterState:
    def __init__(self):
        self.documents = ()
        self.running = False

    def accept_explicit_scan(self, docs):
        if self.running:
            raise RuntimeError('Cannot update document list during registration')
        self.documents = tuple(docs)

    def start_registration(self):
        if self.running:
            raise RuntimeError('Auto Register already running')
        self.running = True

    def finish_registration(self):
        self.running = False
