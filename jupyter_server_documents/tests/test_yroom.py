from __future__ import annotations
import asyncio
import pytest
import pycrdt
from unittest.mock import Mock, MagicMock
from tornado.websocket import WebSocketHandler
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...conftest import MakeYRoom, MakeYRoomManager, MakeRoomFile


def make_mock_websocket() -> MagicMock:
    """Create a MagicMock that passes isinstance(x, WebSocketHandler) checks
    and records all messages written to it."""
    ws = MagicMock(spec=WebSocketHandler)
    ws._messages = []
    ws.write_message.side_effect = lambda msg, binary=False: ws._messages.append(msg)
    ws.ws_connection = True
    return ws


class TestYRoomCallbacks():
    """
    Tests for `YRoom` on_reset and on_stop callback behavior.
    """

    @pytest.mark.asyncio
    async def test_on_reset_callbacks(self, make_yroom: MakeYRoom):
        """
        Asserts that the `on_reset()` callback passed to
        `YRoom.get_{awareness,jupyter_ydoc,ydoc}()` methods are each called with
        the expected object when the YDoc is reset.
        """
        yroom = await make_yroom()
        
        # Create mock callbacks
        awareness_reset_mock = Mock()
        jupyter_ydoc_reset_mock = Mock()
        ydoc_reset_mock = Mock()
        
        # Call get methods while passing `on_reset` callbacks
        yroom.get_awareness(on_reset=awareness_reset_mock)
        await yroom.get_jupyter_ydoc(on_reset=jupyter_ydoc_reset_mock)
        await yroom.get_ydoc(on_reset=ydoc_reset_mock)
        
        # Assert that each callback has not been called yet
        awareness_reset_mock.assert_not_called()
        jupyter_ydoc_reset_mock.assert_not_called()
        ydoc_reset_mock.assert_not_called()
        
        # Reset the ydoc and get the new expected objects
        yroom._reset_ydoc()
        new_awareness = yroom.get_awareness()
        new_jupyter_ydoc = await yroom.get_jupyter_ydoc()
        new_ydoc = await yroom.get_ydoc()
        
        # Assert that each callback was called exactly once with the expected
        # object
        awareness_reset_mock.assert_called_once_with(new_awareness)
        jupyter_ydoc_reset_mock.assert_called_once_with(new_jupyter_ydoc)
        ydoc_reset_mock.assert_called_once_with(new_ydoc)

    @pytest.mark.asyncio
    async def test_on_stop_callbacks(self, make_yroom: MakeYRoom):
        """
        Asserts that `on_stop` callbacks registered via `add_stop_callback()`
        are called when the room is stopped.
        """
        yroom = await make_yroom()

        stop_mock_1 = Mock()
        stop_mock_2 = Mock()

        yroom.add_stop_callback(stop_mock_1)
        yroom.add_stop_callback(stop_mock_2)

        stop_mock_1.assert_not_called()
        stop_mock_2.assert_not_called()

        yroom.stop()

        stop_mock_1.assert_called_once()
        stop_mock_2.assert_called_once()

    @pytest.mark.asyncio
    async def test_restart_does_not_fire_on_stop(self, make_yroom: MakeYRoom):
        """
        Asserts that `on_stop` callbacks are not called when the room is
        restarted (since restarting passes `restarting=True` to `stop()`).
        """
        yroom = await make_yroom()

        stop_mock = Mock()
        yroom.add_stop_callback(stop_mock)

        yroom.restart()

        stop_mock.assert_not_called()


class TestYRoomInactivity():
    """
    Tests for `YRoom` inactivity timeout behavior.
    """

    @pytest.mark.asyncio
    async def test_custom_inactivity_timeout(self, make_yroom: MakeYRoom):
        """
        Asserts that `inactivity_timeout` can be set via the constructor.
        """
        room = await make_yroom(inactivity_timeout=10)
        assert room.inactivity_timeout == 10

    @pytest.mark.asyncio
    async def test_basic_timeout(self, make_yroom: MakeYRoom):
        """
        Asserts that a room becomes inactive only after `inactivity_timeout`
        elapses.
        """
        room = await make_yroom(inactivity_timeout=1)
        assert room.inactive is False
        await asyncio.sleep(0.6)
        assert room.inactive is False
        await asyncio.sleep(0.6)
        assert room.inactive is True

    @pytest.mark.asyncio
    async def test_set_cell_execution_state_resets_activity(self, make_yroom: MakeYRoom):
        room = await make_yroom(inactivity_timeout=1)
        await asyncio.sleep(0.6)
        room.set_cell_execution_state("cell-1", "busy")
        await asyncio.sleep(0.6)
        assert room.inactive is False

    @pytest.mark.asyncio
    async def test_set_cell_awareness_state_resets_activity(self, make_yroom: MakeYRoom):
        room = await make_yroom(inactivity_timeout=1)
        await asyncio.sleep(0.6)
        room.set_cell_awareness_state("cell-1", "busy")
        await asyncio.sleep(0.6)
        assert room.inactive is False

    @pytest.mark.asyncio
    async def test_restart_resets_activity(self, make_yroom: MakeYRoom):
        room = await make_yroom(inactivity_timeout=1)
        await asyncio.sleep(0.6)
        room.restart()
        await asyncio.sleep(0.6)
        assert room.inactive is False


class TestYRoomAutoRestart():
    """Tests that stopped/freed rooms auto-restart when accessed."""

    async def _make_stopped_room(self, manager, make_room_file):
        """Helper: creates a room via the manager, loads it, then deletes it."""
        room_id = make_room_file()
        room = manager.create_room(room_id)
        await room.file_api.until_content_loaded
        await manager.delete_room(room_id)
        assert room.stopped
        assert not manager.has_room(room_id)
        return room, room_id

    @pytest.mark.asyncio
    async def test_get_jupyter_ydoc_restarts_stopped_room(self, make_yroom_manager: MakeYRoomManager, make_room_file: MakeRoomFile):
        manager = make_yroom_manager()
        room, room_id = await self._make_stopped_room(manager, make_room_file)
        await room.get_jupyter_ydoc()
        assert not room.stopped
        assert manager.has_room(room_id)

    @pytest.mark.asyncio
    async def test_get_ydoc_restarts_stopped_room(self, make_yroom_manager: MakeYRoomManager, make_room_file: MakeRoomFile):
        manager = make_yroom_manager()
        room, room_id = await self._make_stopped_room(manager, make_room_file)
        await room.get_ydoc()
        assert not room.stopped
        assert manager.has_room(room_id)

    @pytest.mark.asyncio
    async def test_get_awareness_restarts_stopped_room(self, make_yroom_manager: MakeYRoomManager, make_room_file: MakeRoomFile):
        manager = make_yroom_manager()
        room, room_id = await self._make_stopped_room(manager, make_room_file)
        room.get_awareness()
        assert not room.stopped
        assert manager.has_room(room_id)

    @pytest.mark.asyncio
    async def test_set_cell_execution_state_restarts_stopped_room(self, make_yroom_manager: MakeYRoomManager, make_room_file: MakeRoomFile):
        manager = make_yroom_manager()
        room, room_id = await self._make_stopped_room(manager, make_room_file)
        room.set_cell_execution_state("cell-1", "busy")
        assert not room.stopped
        assert manager.has_room(room_id)

    @pytest.mark.asyncio
    async def test_set_cell_awareness_state_restarts_stopped_room(self, make_yroom_manager: MakeYRoomManager, make_room_file: MakeRoomFile):
        manager = make_yroom_manager()
        room, room_id = await self._make_stopped_room(manager, make_room_file)
        room.set_cell_awareness_state("cell-1", "busy")
        assert not room.stopped
        assert manager.has_room(room_id)


class TestSyncHandshakeRace:
    """
    Regression tests for infra#307: when a new client connects and the doc is
    mutated during the SYNC_STEP1/SYNC_STEP2 handshake, the new client must
    eventually receive all mutations. Before the fix, broadcasts during the
    handshake gap were silently dropped for desynced clients.
    """

    @pytest.mark.asyncio
    async def test_broadcast_queues_for_desynced_client(self, make_yroom: MakeYRoom):
        """
        Asserts that _broadcast_message queues messages for desynced clients
        instead of dropping them.
        """
        room = await make_yroom()

        # Add a synced client (client A) and a desynced client (client B)
        ws_a = make_mock_websocket()
        ws_b = make_mock_websocket()
        client_a_id = room.clients.add(ws_a)
        client_b_id = room.clients.add(ws_b)
        room.clients.mark_synced(client_a_id)
        # B stays desynced

        client_b = room.clients.get(client_b_id)
        assert not client_b.synced
        assert len(client_b.pending_messages) == 0

        # Mutate the ydoc — this triggers _on_ydoc_update → _broadcast_message
        with room._ydoc.transaction():
            room._ydoc["test_map"] = pycrdt.Map()
            room._ydoc["test_map"]["key"] = "value"

        # Client A (synced) should have received the broadcast
        assert len(ws_a._messages) > 0

        # Client B (desynced) should have the message queued, not delivered
        assert len(ws_b._messages) == 0
        assert len(client_b.pending_messages) > 0

    @pytest.mark.asyncio
    async def test_handshake_replays_queued_messages(self, make_yroom: MakeYRoom):
        """
        Asserts that handle_sync_step1 replays queued messages to the client
        after marking it synced. This is the core fix for infra#307.
        """
        room = await make_yroom()

        # Add client B as desynced
        ws_b = make_mock_websocket()
        client_b_id = room.clients.add(ws_b)

        # Mutate the ydoc multiple times while B is desynced
        for i in range(5):
            with room._ydoc.transaction():
                room._ydoc[f"map_{i}"] = pycrdt.Map()
                room._ydoc[f"map_{i}"]["data"] = f"value_{i}"

        client_b = room.clients.get(client_b_id)
        queued_count = len(client_b.pending_messages)
        assert queued_count > 0, "Should have queued messages while desynced"

        # No messages delivered to the WebSocket yet
        assert len(ws_b._messages) == 0

        # Now simulate B sending SYNC_STEP1 (empty state vector — new client)
        client_doc = pycrdt.Doc()
        sync_step1 = pycrdt.create_sync_message(client_doc)

        # Process the SYNC_STEP1 via handle_message (the same path the
        # message queue processor uses)
        room.handle_message(client_b_id, sync_step1)

        # B should now be synced
        assert client_b.synced

        # B should have received: SYNC_STEP2 + queued replays + SYNC_STEP1
        # At minimum: 1 SYNC_STEP2 + queued_count replays + 1 SYNC_STEP1
        assert len(ws_b._messages) >= queued_count + 2

        # The queued messages should have been cleared
        assert len(client_b.pending_messages) == 0

        # Verify the client doc has all the data after applying all messages
        for msg in ws_b._messages:
            if len(msg) < 2:
                continue
            msg_type = msg[0]
            if msg_type == pycrdt.YMessageType.SYNC:
                try:
                    pycrdt.handle_sync_message(msg[1:], client_doc)
                except Exception:
                    pass  # Some messages may not be applicable

        # Client should have all 5 maps
        for i in range(5):
            assert f"map_{i}" in client_doc, f"Client doc missing map_{i}"

    @pytest.mark.asyncio
    async def test_no_data_loss_during_rapid_mutations(self, make_yroom: MakeYRoom):
        """
        Regression test: simulates the exact infra#307 scenario where an AI
        agent rapidly adds cells while a second browser tab connects.
        All mutations must be received by the new client.
        """
        room = await make_yroom()

        # Client A is already synced (first browser tab)
        ws_a = make_mock_websocket()
        client_a_id = room.clients.add(ws_a)
        room.clients.mark_synced(client_a_id)

        # Add some initial content (simulates cells already created)
        with room._ydoc.transaction():
            room._ydoc["cells"] = pycrdt.Array()
            for i in range(10):
                room._ydoc["cells"].append(f"initial_cell_{i}")

        ws_a._messages.clear()  # reset for clarity

        # Client B connects (second browser tab) — starts as desynced
        ws_b = make_mock_websocket()
        client_b_id = room.clients.add(ws_b)

        # While B is desynced, AI agent rapidly adds 19 more cells
        for i in range(19):
            with room._ydoc.transaction():
                room._ydoc["cells"].append(f"ai_cell_{i}")

        # B sends SYNC_STEP1 with empty state
        client_b_doc = pycrdt.Doc()
        client_b_doc["cells"] = pycrdt.Array()  # declare shared type before sync
        sync_step1 = pycrdt.create_sync_message(client_b_doc)
        room.handle_message(client_b_id, sync_step1)

        # Apply all messages to B's doc
        for msg in ws_b._messages:
            if len(msg) < 2:
                continue
            if msg[0] == pycrdt.YMessageType.SYNC:
                try:
                    pycrdt.handle_sync_message(msg[1:], client_b_doc)
                except Exception:
                    pass

        # B must have ALL 29 cells (10 initial + 19 AI-added)
        b_cells = list(client_b_doc["cells"])
        assert len(b_cells) == 29, (
            f"Client B has {len(b_cells)} cells, expected 29. "
            f"Missing cells indicate data loss during sync handshake."
        )

    @pytest.mark.asyncio
    async def test_no_exception_during_handshake_with_mutations(self, make_yroom: MakeYRoom):
        """
        Regression test for infra#300: concurrent mutations during sync
        handshake must not cause crashes (e.g., findIndexSS 'Unexpected case').
        """
        room = await make_yroom()

        # Synced client A
        ws_a = make_mock_websocket()
        client_a_id = room.clients.add(ws_a)
        room.clients.mark_synced(client_a_id)

        # Add initial doc state
        with room._ydoc.transaction():
            room._ydoc["data"] = pycrdt.Map()
            room._ydoc["data"]["counter"] = 0

        # Connect multiple desynced clients, mutate doc, then sync them all
        desynced_clients = []
        for _ in range(5):
            ws = make_mock_websocket()
            cid = room.clients.add(ws)
            desynced_clients.append((ws, cid))

        # Rapid mutations while all 5 clients are desynced
        for i in range(50):
            with room._ydoc.transaction():
                room._ydoc["data"]["counter"] = i

        # Sync all clients — no exceptions should be raised
        for ws, cid in desynced_clients:
            client_doc = pycrdt.Doc()
            client_doc["data"] = pycrdt.Map()  # declare shared type before sync
            sync_step1 = pycrdt.create_sync_message(client_doc)
            room.handle_message(cid, sync_step1)

            # Apply messages to client doc — no exceptions
            for msg in ws._messages:
                if len(msg) < 2:
                    continue
                if msg[0] == pycrdt.YMessageType.SYNC:
                    pycrdt.handle_sync_message(msg[1:], client_doc)

            # All clients must see the final counter value
            assert client_doc["data"]["counter"] == 49

    @pytest.mark.asyncio
    @pytest.mark.parametrize("num_mutations", [10, 50, 100])
    @pytest.mark.parametrize("num_clients", [2, 5])
    async def test_concurrent_mutations_stress(
        self, make_yroom: MakeYRoom, num_mutations: int, num_clients: int
    ):
        """
        Stress test: N clients connect while the doc is being mutated.
        All clients must converge to the same final state.
        """
        room = await make_yroom()

        # Pre-populate with a cells array
        with room._ydoc.transaction():
            room._ydoc["cells"] = pycrdt.Array()

        # Connect N desynced clients
        clients = []
        for _ in range(num_clients):
            ws = make_mock_websocket()
            cid = room.clients.add(ws)
            clients.append((ws, cid))

        # Apply num_mutations while all clients are desynced
        for i in range(num_mutations):
            with room._ydoc.transaction():
                room._ydoc["cells"].append(f"cell_{i}")

        # Sync all clients
        for ws, cid in clients:
            client_doc = pycrdt.Doc()
            client_doc["cells"] = pycrdt.Array()  # declare shared type before sync
            sync_step1 = pycrdt.create_sync_message(client_doc)
            room.handle_message(cid, sync_step1)

            for msg in ws._messages:
                if len(msg) < 2:
                    continue
                if msg[0] == pycrdt.YMessageType.SYNC:
                    try:
                        pycrdt.handle_sync_message(msg[1:], client_doc)
                    except Exception:
                        pass

            cells = list(client_doc["cells"])
            assert len(cells) == num_mutations, (
                f"Client has {len(cells)} cells, expected {num_mutations}"
            )
