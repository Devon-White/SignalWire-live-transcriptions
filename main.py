import os
import json
import base64
from quart import Quart, websocket
from pyngrok import ngrok
from dotenv import load_dotenv
from deepgram import Deepgram
from signalwire.voice_response import VoiceResponse, Start, Stream, Dial
from signalwire.rest import Client as SignalwireClient
from loguru import logger
from pydub import AudioSegment

# Load environment variables
load_dotenv()

# Initiate Quart app
app = Quart(__name__)

# Update app configurations from environment variables
app.config.update(
    TO_NUMBER=os.getenv("TO_NUMBER"),
    WEBHOOK_NUMBER=os.getenv("WEBHOOK_NUM"),
    PORT=os.getenv('PORT'),
    PROJECT=os.getenv('PROJECT'),
    SW_TOKEN=os.getenv('SW_TOKEN'),
    SPACE=os.getenv('SPACE'),
    dg_client=Deepgram(os.getenv('DEEPGRAM_TOKEN')),
    PUBLIC_URL=None,
)

# Initiate Signalwire client
client = SignalwireClient(app.config['PROJECT'], app.config['SW_TOKEN'], signalwire_space_url=f"{app.config['SPACE']}")


class ActiveCall:
    # Class to handle active calls

    def __init__(self, sid: str, dg_client: Deepgram):
        self.sid = sid
        self.dg_client = dg_client

    async def get_transcript(self, data: dict):
        # Get transcript from the provided data dictionary
        transcript = data.get('channel', {}).get('alternatives', [{}])[0].get('transcript')
        if transcript:
            # Logs Call sid and transcription
            logger.info(f"{self.sid} - {transcript}")

    async def connect_to_deepgram(self):
        # Establish a connection with Deepgram
        socket = await self.dg_client.transcription.live({
            'punctuate': True,
            'encoding': "mulaw",    # Match encoding of phone calls
            'sample_rate': 8000,    # Match audio sample rate
            'channels': 2,          # Match Audio Channel amount
            'model': 'phonecall',   # Improves accuracy of transcribing phone call audio
            'language': 'en-US',    # Sets language of transcription to english
            'tier': 'nova',         # Sets transcription tier to Nova - tiers: standard/enhanced/nova
            'interim_results': False,   # Only gives transcription results on final speech (when silence is heard)
        })
        socket.registerHandler(socket.event.CLOSE, lambda _: logger.info("Connection Closed..."))
        socket.registerHandler(socket.event.TRANSCRIPT_RECEIVED, self.get_transcript)
        return socket


# Handles inbound calls
@app.route('/inbound', methods=['POST', 'GET'])
async def inbound_call():
    # Swap public url from a http url, to a wss url
    public_url = app.config.get('PUBLIC_URL')
    public_url = public_url.replace("https", "wss").replace("http", "wss") + '/media'

    # Start Stream
    response = VoiceResponse()
    start = Start()
    stream = Stream(name='stream', url=public_url, track="both_tracks")
    start.append(stream)
    response.append(start)

    # Forward call
    dial = Dial()
    dial.number(f"{app.config['TO_NUMBER']}")
    response.append(dial)

    return response.to_xml()


@app.websocket('/media')
async def websocket_endpoint():
    # Handle media websocket endpoint, SignalWire will stream call audio to this endpoint.
    deepgram_socket = None
    in_buffer = bytearray()
    out_buffer = bytearray()
    buffer_size = 20 * 160
    try:
        while True:
            ws = await websocket.receive()
            # Makes sure valid json is being sent
            data = json.loads(ws)
            logger.error("Invalid JSON received.")
            event = data.get('event')

            if event == "start":
                sid = data.get('start', {}).get('callSid')
                if sid:
                    # initializes a new ActiveCall, and then makes a connection to Deepgram
                    call_class = ActiveCall(sid, app.config["dg_client"])
                    deepgram_socket = await call_class.connect_to_deepgram()
                    logger.info(f"{sid} - Session is starting...")

            elif event == "media":
                # Decode base64 payload into bytes and then extend the audio bytes to the correlating bytearray
                payload = base64.b64decode(data.get('media', {}).get('payload', ''))
                track = data.get('media', {}).get('track')

                if track == 'inbound':
                    in_buffer.extend(payload)
                if track == 'outbound':
                    out_buffer.extend(payload)

            elif event == "stop":
                if deepgram_socket is not None:
                    # Sending an empty byte will close the connection with Deepgram
                    deepgram_socket.send(b'')
                break

            """
            Checks the length of the bytearrays, once both are the length of the buffer size, we will mix the two
            audio channels together to make a stereo audio segment. Once this segment is created, we will then send the 
            raw data of this stereo segment to DeepGram for transcription
            """
            while len(in_buffer) >= buffer_size and len(out_buffer) >= buffer_size:
                as_inbound = AudioSegment(bytes(in_buffer[:buffer_size]), sample_width=1, frame_rate=8000, channels=1)
                as_outbound = AudioSegment(bytes(out_buffer[:buffer_size]), sample_width=1, frame_rate=8000, channels=1)
                mixed = AudioSegment.from_mono_audiosegments(as_inbound, as_outbound)
                deepgram_socket.send(mixed.raw_data)

                in_buffer = in_buffer[buffer_size:]
                out_buffer = out_buffer[buffer_size:]

    except Exception as e:
        logger.error(e)
    finally:
        await websocket.close(app.config['PORT'])


def start_ngrok():
    """Start ngrok for tunneling"""
    tunnel_url = ngrok.connect(app.config['PORT']).public_url
    app.config['PUBLIC_URL'] = tunnel_url

    # Getting sid of webhook number
    incoming_phone_numbers = client.incoming_phone_numbers.list(phone_number=app.config['WEBHOOK_NUMBER'])
    sid = incoming_phone_numbers[0].sid if incoming_phone_numbers else logger.error("Invalid Webhook number")

    # Update the voice URL
    # noinspection PyTypeChecker
    client.incoming_phone_numbers(sid).update(voice_url=f"{tunnel_url}/inbound", voice_receive_mode="voice")


if __name__ == "__main__":
    start_ngrok()
    app.run('localhost', port=app.config['PORT'])
