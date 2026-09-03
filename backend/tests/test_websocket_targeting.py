from utils.websocket import WebSocketManager


class _Socket:
    def __init__(self):
        self.messages = []

    async def send_text(self, message):
        self.messages.append(message)


async def test_generator_message_is_sent_only_to_registered_socket():
    manager = WebSocketManager()
    socket_a = _Socket()
    socket_b = _Socket()
    manager.active_connections.extend([socket_a, socket_b])
    manager.register_generator_instance(socket_a, "generator-a")
    manager.register_generator_instance(socket_b, "generator-b")

    assert await manager.send_to_generator_instance(
        "generator-b", "generation_request_work", {"reservation_id": "one"}
    ) is True
    assert socket_a.messages == []
    assert len(socket_b.messages) == 1
