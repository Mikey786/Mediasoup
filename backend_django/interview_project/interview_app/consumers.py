# backend_django/interview_app/consumers.py
import json
import httpx
from channels.generic.websocket import AsyncWebsocketConsumer
from django.conf import settings
from asgiref.sync import sync_to_async
from .models import Room, Participant
import traceback # For detailed error logging

# --- Database Interaction Helpers (Correctly Defined) ---
@sync_to_async
def get_room_and_participant_for_connect_db(room_name, client_id):
    print(f"DB_HELPER: get_room_and_participant_for_connect_db - room_name='{room_name}', client_id='{client_id}'")
    room, created = Room.objects.get_or_create(name=room_name)
    is_host_flag = False
    default_display_name = f"User-{client_id[:5]}"
    current_display_name = default_display_name

    if created:
        print(f"DB_HELPER: Room '{room_name}' created.")
        room.host_client_id = client_id
        room.save() 
        is_host_flag = True
        current_display_name = "Host"
    elif not room.host_client_id:
        print(f"DB_HELPER: Room '{room_name}' existed but had no host. Assigning host.")
        room.host_client_id = client_id
        room.save()
        is_host_flag = True
        current_display_name = "Host"
    elif room.host_client_id == client_id:
        print(f"DB_HELPER: Client '{client_id}' is rejoining as HOST for room '{room_name}'.")
        is_host_flag = True
        try:
            existing_participant = Participant.objects.get(client_id=client_id, room=room)
            current_display_name = existing_participant.display_name
            print(f"DB_HELPER: Rejoining host found existing name: '{current_display_name}'")
        except Participant.DoesNotExist:
            current_display_name = "Host" 
            print(f"DB_HELPER: Rejoining host, no previous participant record for name, defaulting to 'Host'")
    else: # Attendee
        print(f"DB_HELPER: Client '{client_id}' is joining as ATTENDEE for room '{room_name}'.")
        try:
            existing_participant = Participant.objects.get(client_id=client_id, room=room)
            current_display_name = existing_participant.display_name
            print(f"DB_HELPER: Rejoining attendee found existing name: '{current_display_name}'")
        except Participant.DoesNotExist:
            print(f"DB_HELPER: New attendee, using default name: '{current_display_name}'")
            pass 
    
    participant, p_created = Participant.objects.update_or_create(
        client_id=client_id,
        defaults={'room': room, 'display_name': current_display_name, 'is_host': is_host_flag}
    )
    if p_created:
        print(f"DB_HELPER: Participant record CREATED for '{client_id}'. is_host: {is_host_flag}, name: '{current_display_name}'")
    else:
        print(f"DB_HELPER: Participant record UPDATED for '{client_id}'. is_host: {is_host_flag}, name: '{current_display_name}'")
    return room, participant, is_host_flag, current_display_name

@sync_to_async
def save_room_rtp_capabilities_db(room_instance, rtp_caps):
    print(f"DB_HELPER: save_room_rtp_capabilities_db for room '{room_instance.name if room_instance else 'None'}'")
    if rtp_caps and room_instance:
        room_instance.router_rtp_capabilities = rtp_caps
        room_instance.save()
        print(f"DB_HELPER: RTP capabilities saved for room '{room_instance.name}'.")
        return True
    print(f"DB_HELPER: Failed to save RTP capabilities (no rtp_caps or room_instance).")
    return False

@sync_to_async
def get_host_participant_info_db(room_instance):
    print(f"DB_HELPER: get_host_participant_info_db for room '{room_instance.name if room_instance else 'None'}' with host_client_id '{room_instance.host_client_id if room_instance else 'N/A'}'")
    if room_instance and room_instance.host_client_id:
        host = Participant.objects.filter(room=room_instance, client_id=room_instance.host_client_id, is_host=True).first()
        print(f"DB_HELPER: Host participant found: {host.display_name if host else 'None'}")
        return host
    return None

@sync_to_async
def handle_participant_disconnect_db_ops(client_id_to_remove):
    print(f"DB_HELPER: handle_participant_disconnect_db_ops for client_id='{client_id_to_remove}'")
    participant_to_remove = Participant.objects.select_related('room').filter(client_id=client_id_to_remove).first()
    room_obj = None
    host_left_room = False

    if participant_to_remove:
        room_obj = participant_to_remove.room 
        is_actually_host = participant_to_remove.is_host
        
        print(f"DB_HELPER: Attempting to delete participant {client_id_to_remove} (was_host={is_actually_host}) from room {room_obj.name if room_obj else 'Unknown'}")
        participant_to_remove.delete()
        print(f"DB_HELPER: Participant {client_id_to_remove} removed.")

        if is_actually_host and room_obj:
            # Re-fetch to ensure no stale data if concurrent ops were possible, though less likely here.
            # room_obj_fresh = Room.objects.get(pk=room_obj.pk)
            if room_obj.host_client_id == client_id_to_remove: # Check if this was indeed the current host
                room_obj.host_client_id = None 
                room_obj.save()
                host_left_room = True
                print(f"DB_HELPER: Host {client_id_to_remove} left room {room_obj.name}, host_client_id cleared.")
    else:
        print(f"DB_HELPER: Participant {client_id_to_remove} not found for deletion.")
        
    return room_obj, host_left_room

@sync_to_async
def update_participant_display_name_db_ops(client_id_val, new_name_val):
    print(f"DB_HELPER: update_participant_display_name_db_ops for client_id='{client_id_val}', new_name='{new_name_val}'")
    participant = Participant.objects.select_related('room').get(client_id=client_id_val)
    participant.display_name = new_name_val
    participant.save()
    print(f"DB_HELPER: Display name updated for '{client_id_val}'.")
    return participant

@sync_to_async
def get_participant_is_host_db_ops(client_id_val):
    print(f"DB_HELPER: get_participant_is_host_db_ops for client_id='{client_id_val}'")
    try: 
        is_host = Participant.objects.get(client_id=client_id_val).is_host
        print(f"DB_HELPER: Client '{client_id_val}' is_host: {is_host}")
        return is_host
    except Participant.DoesNotExist: 
        print(f"DB_HELPER: Client '{client_id_val}' not found, returning is_host=False.")
        return False

@sync_to_async
def get_participant_room_from_instance_db_ops(participant_instance):
    print(f"DB_HELPER: get_participant_room_from_instance_db_ops for participant '{participant_instance.client_id if participant_instance else 'None'}'")
    if participant_instance:
        room = participant_instance.room # Accessing the related field
        print(f"DB_HELPER: Room found: '{room.name if room else 'None'}'")
        return room
    return None


@sync_to_async
def get_participant_list_for_room_db_ops(room_obj):
    print(f"DB_HELPER: get_participant_list_for_room_db_ops for room '{room_obj.name if room_obj else 'None'}'")
    if not room_obj: return []
    participants = list(Participant.objects.filter(room=room_obj).values('client_id', 'display_name', 'is_host').order_by('-is_host', 'display_name'))
    print(f"DB_HELPER: Participant list: {participants}")
    return participants
# --- End Database Interaction Helpers ---


async def mediasoup_request(method, endpoint, data=None):
    url = f"{settings.MEDIASOUP_NODE_URL}{endpoint}"
    log_data = data 
    if data:
        log_data_copy = dict(data) # Create a copy to modify for logging
        if 'dtlsParameters' in log_data_copy and isinstance(log_data_copy['dtlsParameters'], dict):
            log_data_copy['dtlsParameters'] = {**log_data_copy['dtlsParameters'], 'fingerprints': '[REDACTED]'}
        if 'rtpParameters' in log_data_copy: log_data_copy['rtpParameters'] = '[REDACTED_DICT]'
        if 'rtpCapabilities' in log_data_copy: log_data_copy['rtpCapabilities'] = '[REDACTED_DICT]'
        log_data_str = str(log_data_copy)[:300] # Log a snippet
    else:
        log_data_str = "None"

    print(f"Consumer: Mediasoup request. Method: {method}, URL: {url}, Data: {log_data_str}...")
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            if method == 'GET': response = await client.get(url)
            elif method == 'POST': response = await client.post(url, json=data) # httpx handles json for 'json='
            else: raise ValueError(f"Unsupported HTTP method: {method}")
            
            response_text_snippet = response.text[:200] if response.text else "None"
            print(f"Consumer: Mediasoup response status: {response.status_code}, Content snippet: {response_text_snippet}...")
            response.raise_for_status() 
            
            if response.status_code == 204:
                print(f"Consumer: Mediasoup request to {endpoint} returned 204 No Content.")
                return {'success': True, 'message': 'Operation successful with 204 No Content.'} 
            
            content_type = response.headers.get('content-type','').lower()
            is_json_response = 'application/json' in content_type

            if not response.content or not response.text.strip():
                print(f"Consumer: Mediasoup request to {endpoint} returned {response.status_code} with empty body.")
                if 200 <= response.status_code < 300:
                    return {'success': True, 'message': f'Request to {endpoint} successful (status {response.status_code}) with empty body.'}
                return None # Should have been caught by raise_for_status if not 2xx

            if 200 <= response.status_code < 300 and not is_json_response:
                 print(f"Consumer: Mediasoup request to {endpoint} returned {response.status_code} with non-JSON body: '{response.text.strip()}'")
                 return {'success': True, 'message': f'Request to {endpoint} successful (status {response.status_code}) with non-JSON body.'}

            if is_json_response:
                return response.json()
            else: # Fallback if content exists but isn't JSON and wasn't caught above
                print(f"Consumer: Mediasoup request to {endpoint} has content but not JSON. Status: {response.status_code}. Treating as simple success if 2xx.")
                if 200 <= response.status_code < 300:
                    return {'success': True, 'message': 'Operation successful, non-JSON content.'}
                # This path should ideally not be hit if raise_for_status works for non-2xx.
                raise Exception(f"Unexpected non-JSON response with status {response.status_code} for {endpoint}")

        except httpx.HTTPStatusError as e:
            print(f"Consumer: HTTP error from Mediasoup Node.js for {endpoint}: Status {e.response.status_code} - Response: {e.response.text[:500]}")
            try: error_json = json.loads(e.response.text); raise Exception(error_json.get("error", e.response.text))
            except json.JSONDecodeError: raise 
        except httpx.RequestError as e: print(f"Consumer: Network/Request error calling Mediasoup Node.js for {endpoint}: {e}"); raise
        except json.JSONDecodeError as e: 
            print(f"Consumer: JSONDecodeError parsing Mediasoup Node.js response for {endpoint}. Status: {response.status_code}, Content: {response.text[:500]}. Error: {e}")
            if 200 <= response.status_code < 300: return {'success': True, 'message': 'Response not JSON but status OK (JSON parse failed).'} # Should be caught by earlier checks ideally
            raise 

class InterviewConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_name = self.scope['url_route']['kwargs']['room_name']
        self.client_id = self.scope['url_route']['kwargs']['client_id'] 
        self.room_group_name = f'interview_{self.room_name}'
        self.is_host = False 
        self.display_name = ""
        self.participant_instance = None 
        self.room_instance = None

        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()
        print(f"Consumer CONNECT: Client {self.client_id} attempting to connect to room {self.room_name}")

        try:
            self.room_instance, self.participant_instance, self.is_host, self.display_name = \
                await get_room_and_participant_for_connect_db(self.room_name, self.client_id)
            
            print(f"Consumer CONNECT: Client {self.client_id} is {'HOST' if self.is_host else 'ATTENDEE'}. Name: '{self.display_name}'")

            await self.send_json({'type': 'roleAssignment', 'data': {'isHost': self.is_host, 'clientId': self.client_id, 'displayName': self.display_name}})

            if not self.room_instance.router_rtp_capabilities:
                print(f"Consumer CONNECT: Fetching routerRtpCapabilities for room {self.room_name}")
                rtp_caps = await mediasoup_request('GET', f'/rooms/{self.room_name}/router-rtp-capabilities')
                if not await save_room_rtp_capabilities_db(self.room_instance, rtp_caps):
                    print(f"Consumer CONNECT: ERROR - Failed to fetch or save routerRtpCapabilities for room {self.room_name}")
                    raise Exception("Failed to initialize room capabilities.")
            
            await self.send_json({'type': 'routerRtpCapabilities', 'data': self.room_instance.router_rtp_capabilities})
            await self.broadcast_participant_list(self.room_instance)
            
            if not self.is_host and self.room_instance.host_client_id:
                host_participant_db = await get_host_participant_info_db(self.room_instance)
                if host_participant_db:
                    print(f"Consumer CONNECT: Attendee {self.client_id} - Sending hostInformation for host {host_participant_db.client_id}")
                    await self.send_json({
                        'type': 'hostInformation',
                        'data': {'hostClientId': host_participant_db.client_id, 'hostDisplayName': host_participant_db.display_name}
                    })
                    try:
                        print(f"Consumer CONNECT: Attendee {self.client_id} - Fetching existing producers for host {self.room_instance.host_client_id}.")
                        host_producers = await mediasoup_request('GET', f'/rooms/{self.room_name}/clients/{self.room_instance.host_client_id}/producers')
                        if host_producers and isinstance(host_producers, list):
                            print(f"Consumer CONNECT: Attendee {self.client_id} - Host has {len(host_producers)} active producers.")
                            for producer_info in host_producers:
                                if producer_info.get('appData', {}).get('isHostProducer'):
                                    print(f"Consumer CONNECT: Sending existing host producer {producer_info.get('producerId')} (kind: {producer_info.get('kind')}) to attendee {self.client_id}")
                                    await self.send_json({'type': 'newProducer', 'data': { 'clientId': self.room_instance.host_client_id, 'producerId': producer_info.get('producerId'), 'kind': producer_info.get('kind'), 'appData': producer_info.get('appData', {})}})
                                else:
                                    print(f"Consumer CONNECT: Attendee {self.client_id} - Skipping producer, not marked as host producer: {producer_info.get('producerId')}")
                        elif not host_producers:
                            print(f"Consumer CONNECT: Attendee {self.client_id} - Host {self.room_instance.host_client_id} has no active producers.")
                        else:
                            print(f"Consumer CONNECT: Attendee {self.client_id} - Warning: Received unexpected format for host producers: {host_producers}")
                    except Exception as e_prod:
                        print(f"Consumer CONNECT: Attendee {self.client_id} - Error fetching host producers: {e_prod}")
            
            print(f"Consumer CONNECT: Client {self.client_id} successfully connected and configured.")

        except Exception as e:
            print(f"Consumer CONNECT: FATAL Error for {self.client_id} in room {self.room_name}: {e}")
            traceback.print_exc()
            try: # Try to send error before closing
                await self.send_json({'type': 'error', 'message': f"Server connection setup error: {str(e)}"})
            except Exception as send_e:
                print(f"Consumer CONNECT: Error sending final error message: {send_e}")
            await self.close(code=4001)

    async def disconnect(self, close_code):
        print(f"Consumer DISCONNECT: Client {self.client_id} from room {self.room_name}. Code: {close_code}")
        try:
            room_after_disconnect, host_left_flag = await handle_participant_disconnect_db_ops(self.client_id)

            if host_left_flag:
                 print(f"Consumer DISCONNECT: Host {self.client_id} left, broadcasting hostLeft.")
                 await self.channel_layer.group_send( self.room_group_name, {'type': 'broadcast_message', 'message': {'type': 'hostLeft', 'data': {'clientId': self.client_id}}})

            print(f"Consumer DISCONNECT: Notifying Mediasoup for client {self.client_id}.")
            await mediasoup_request('POST', f'/rooms/{self.room_name}/clients/{self.client_id}/disconnected') 
            
            if room_after_disconnect: 
                print(f"Consumer DISCONNECT: Broadcasting updated participant list for room {room_after_disconnect.name}.")
                await self.broadcast_participant_list(room_after_disconnect)
            else: 
                print(f"Consumer DISCONNECT: No room context after DB ops, broadcasting generic peerClosed for {self.client_id}.")
                await self.channel_layer.group_send( self.room_group_name, {'type': 'broadcast_message', 'message': {'type': 'peerClosed', 'data': {'clientId': self.client_id}}})
        except Exception as e:
            print(f"Consumer DISCONNECT: Error for {self.client_id}: {e}"); traceback.print_exc()
        finally:
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)
            print(f"Consumer DISCONNECT: Client {self.client_id} removed from group {self.room_group_name}.")


    async def receive(self, text_data):
        message = json.loads(text_data)
        payload_type = message.get('type')
        payload_data = message.get('data', {})
        print(f"Consumer RECEIVE: From {self.client_id} ({'Host' if self.is_host else 'Attendee'}): {payload_type}")

        try:
            if payload_type == 'updateDisplayName':
                new_name = payload_data.get('displayName', '').strip()
                print(f"Consumer RECEIVE updateDisplayName: New name '{new_name}' for {self.client_id}")
                if 3 <= len(new_name) <= 25: 
                    updated_participant = await update_participant_display_name_db_ops(self.client_id, new_name)
                    self.display_name = updated_participant.display_name 
                    self.participant_instance = updated_participant 
                    await self.send_json({'type': 'displayNameUpdated', 'data': {'clientId': self.client_id, 'displayName': self.display_name}})
                    participant_room = await get_participant_room_from_instance_db_ops(updated_participant)
                    await self.broadcast_participant_list(participant_room)
                else:
                    await self.send_json({'type': 'error', 'message': 'Invalid display name length (3-25 chars).', 'requestType': payload_type})

            elif payload_type == 'createWebRtcTransport':
                print(f"Consumer RECEIVE createWebRtcTransport: Purpose: {payload_data.get('purpose')}")
                transport_options = await mediasoup_request('POST', f'/rooms/{self.room_name}/clients/{self.client_id}/transports')
                await self.send_json({'type': 'transportCreated', 'data': transport_options})

            elif payload_type == 'connectTransport':
                transport_id = payload_data.get('transportId'); dtls_parameters = payload_data.get('dtlsParameters')
                print(f"Consumer RECEIVE connectTransport: For transport_id {transport_id}")
                connect_result = await mediasoup_request('POST', f'/rooms/{self.room_name}/clients/{self.client_id}/transports/{transport_id}/connect', data={'dtlsParameters': dtls_parameters})
                if connect_result and connect_result.get('success'): 
                    await self.send_json({'type': 'transportConnected', 'data': {'transportId': transport_id}})
                    print(f"Consumer RECEIVE connectTransport: Relayed successfully for {transport_id}.")
                else: 
                    print(f"Consumer RECEIVE connectTransport: Node.js call failed/unexpected for {transport_id}: {connect_result}")
                    await self.send_json({'type': 'error', 'message': 'Transport connection failure (server).', 'requestType': payload_type, 'data': {'transportId': transport_id}})


            elif payload_type == 'produce':
                is_currently_host = await get_participant_is_host_db_ops(self.client_id)
                self.is_host = is_currently_host 
                print(f"Consumer RECEIVE produce: Client {self.client_id} is_host check: {is_currently_host}")
                if not is_currently_host:
                    print(f"Consumer RECEIVE produce: Denied for attendee {self.client_id}."); await self.send_json({'type': 'error', 'message': 'Only host can share media.', 'requestType': payload_type}); return
                
                transport_id = payload_data.get('transportId'); kind = payload_data.get('kind'); rtp_parameters = payload_data.get('rtpParameters'); app_data = payload_data.get('appData', {}); app_data['isHostProducer'] = True 
                producer_info = await mediasoup_request('POST', f'/rooms/{self.room_name}/clients/{self.client_id}/transports/{transport_id}/produce', data={'kind': kind, 'rtpParameters': rtp_parameters, 'appData': app_data})
                if producer_info and producer_info.get('id'): 
                    print(f"Consumer RECEIVE produce: Producer created on Node.js: {producer_info.get('id')}")
                    await self.send_json({'type': 'produced', 'data': {'producerId': producer_info['id'], 'kind': kind, 'clientId': self.client_id}})
                    await self.channel_layer.group_send(self.room_group_name, {'type': 'broadcast_message', 'message': {'type': 'newProducer', 'data': {'clientId': self.client_id, 'producerId': producer_info['id'], 'kind': kind, 'appData': app_data}}})
                else: 
                    print(f"Consumer RECEIVE produce: Failed to get producerId from Node.js."); await self.send_json({'type': 'error', 'message': 'Failed to create producer on server.', 'requestType': payload_type})
            
            elif payload_type == 'closeProducer': 
                is_currently_host = await get_participant_is_host_db_ops(self.client_id)
                self.is_host = is_currently_host
                if not is_currently_host: await self.send_json({'type': 'error', 'message': 'Only host can manage producers.', 'requestType': payload_type}); return
                producer_id_to_close = payload_data.get('producerId'); print(f"Consumer RECEIVE closeProducer: Host {self.client_id} for producer {producer_id_to_close}.")
                await self.channel_layer.group_send(self.room_group_name, {'type': 'broadcast_message', 'message': {'type': 'producerClosed', 'data': { 'clientId': self.client_id, 'producerId': producer_id_to_close }}})

            elif payload_type == 'consume':
                transport_id = payload_data.get('transportId'); producer_id_to_consume = payload_data.get('producerId'); rtp_capabilities = payload_data.get('rtpCapabilities'); app_data = payload_data.get('appData', {})
                print(f"Consumer RECEIVE consume: Client {self.client_id} for producer {producer_id_to_consume}")
                consumer_params = await mediasoup_request('POST', f'/rooms/{self.room_name}/clients/{self.client_id}/transports/{transport_id}/consume', data={'producerId': producer_id_to_consume, 'rtpCapabilities': rtp_capabilities, 'appData': app_data})
                if consumer_params and consumer_params.get('id'): # Check for consumer ID specifically
                    await self.send_json({'type': 'consumed', 'data': consumer_params})
                else: 
                    print(f"Consumer RECEIVE consume: Failed to get consumer params for {producer_id_to_consume}. Result: {consumer_params}"); 
                    await self.send_json({'type': 'error', 'message': 'Failed to create consumer on server.', 'requestType': payload_type, 'data': {'producerId': producer_id_to_consume}})


            elif payload_type == 'resumeConsumer':
                consumer_id = payload_data.get('consumerId')
                print(f"Consumer RECEIVE resumeConsumer: For consumer_id {consumer_id}")
                resume_result = await mediasoup_request('POST', f'/rooms/{self.room_name}/clients/{self.client_id}/consumers/{consumer_id}/resume')
                if resume_result and resume_result.get('success'): 
                    await self.send_json({'type': 'consumerResumed', 'data': {'consumerId': consumer_id}})
                    print(f"Consumer RECEIVE resumeConsumer: Relayed successfully for {consumer_id}.")
                else: 
                    print(f"Consumer RECEIVE resumeConsumer: Node.js call failed/unexpected for {consumer_id}: {resume_result}")
                    await self.send_json({'type': 'error', 'message': 'Consumer resume failure (server).', 'requestType': payload_type, 'data': {'consumerId': consumer_id}})
            
            else:
                print(f"Consumer RECEIVE: Unknown message type from {self.client_id}: {payload_type}")

        except Participant.DoesNotExist:
            print(f"Consumer RECEIVE: Participant {self.client_id} not found. Critical error or disconnected."); traceback.print_exc()
            await self.send_json({'type': 'error', 'message': 'Session error or participant not found. Please rejoin.', 'requestType': payload_type})
            await self.close(code=4002) 
        except Exception as e: 
            err_msg = f"Error processing message type {payload_type} for {self.client_id}: {str(e)}"
            traceback.print_exc()
            print(f"Consumer RECEIVE: {err_msg}")
            await self.send_json({'type': 'error', 'message': err_msg, 'requestType': payload_type})

    async def broadcast_message(self, event):
        message = event['message']
        sender_channel_name = event.get('sender_channel_name')
        # print(f"Consumer BROADCAST_MESSAGE: Type '{message.get('type')}' to group {self.room_group_name}. Sender: {sender_channel_name}, Self: {self.channel_name}")
        if (sender_channel_name != self.channel_name) or (message.get("type") == "participantList"):
            await self.send(text_data=json.dumps(message))

    async def broadcast_participant_list(self, room_obj_param):
        room_to_query = None
        if isinstance(room_obj_param, Room): room_to_query = room_obj_param
        elif isinstance(room_obj_param, str): 
            try: room_to_query = await sync_to_async(Room.objects.get)(name=room_obj_param)
            except Room.DoesNotExist: print(f"Consumer BROADCAST_PARTICIPANT_LIST: Room {room_obj_param} not found."); return
        
        if not room_to_query: print("Consumer BROADCAST_PARTICIPANT_LIST: Room object is None/invalid."); return
        
        try:
            participants_list_data = await get_participant_list_for_room_db_ops(room_to_query)
            # print(f"Consumer BROADCAST_PARTICIPANT_LIST: For room {room_to_query.name}: {participants_list_data}")
            await self.channel_layer.group_send(
                self.room_group_name, 
                {'type': 'broadcast_message', 'message': {'type': 'participantList', 'data': participants_list_data}}
            )
        except Exception as e:
            print(f"Consumer BROADCAST_PARTICIPANT_LIST: Error for room {room_to_query.name if room_to_query else 'Unknown'}: {e}"); traceback.print_exc()

    async def send_json(self, data):
        if self.channel_layer is None or self.channel_name is None: 
            print(f"Consumer SEND_JSON: Channel layer/name is None for {self.client_id}. Cannot send: {data.get('type')}")
            return
        try:
            # print(f"Consumer SEND_JSON: To {self.client_id}: {data.get('type')}") # Reduce verbosity if too much
            await self.send(text_data=json.dumps(data))
        except Exception as e: # Catch potential errors during send if channel closes abruptly
            print(f"Consumer SEND_JSON: Error for {self.client_id} sending {data.get('type')}: {e}")