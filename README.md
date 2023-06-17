# SignalWire and Deepgram Transcription Service

This script integrates SignalWire's telephony and Deepgram's transcription services. It listens for inbound calls, forwards them, streams the conversation, decodes the payload, and then sends it to Deepgram for transcription. Finally, the transcription result is logged.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Setup](#setup)
3. [Code Explanation](#code-explanation)
    - [ActiveCall Class](#activecall-class)
    - [Key Functions](#key-functions-explanation)
4. [Running the Script](#running-the-script)

## Prerequisites

- Python 3.7 or higher
- A [SignalWire account](https://developer.signalwire.com/guides/signing-up-for-a-space) with:
    - Space URL
    - Project ID
    - [Authentication Token](https://developer.signalwire.com/guides/navigating-your-space#api)
- A [Deepgram account](https://console.deepgram.com/signup) with:
    - API Token
- A [Ngrok account](https://dashboard.ngrok.com/login) with:
  - [auth-token](https://dashboard.ngrok.com/get-started/setup)
    
- The following Python packages installed:
    - quart
    - pyngrok
    - python-dotenv
    - deepgram
    - signalwire
    - loguru
    - pydub
    - requests

## Setup

First, install all necessary Python packages:

Run the following command to install the Deepgram package.
```commandline
pip install deepgram-sdk
```

Then, run the requirements.txt file to install the rest of the dependencies:

```commandline
pip install -r requirements.txt
```

Then, create a `.env` file to hold your environment variables (Project ID, Auth Token, etc). This .env file should contain the following fields:

```dotenv
TO_NUMBER='Number you Wish to Dial To'
WEBHOOK_NUM='SignalWire Number that will host your webhooks'
PORT=3000
PROJECT='SignalWire Project ID'
SW_TOKEN='SignalWire API Token'
SPACE='SignalWire space url: example.signalwire.com'
DEEPGRAM_TOKEN='Deepgram API Token'
```


Fill in the necessary values from your SignalWire and Deepgram accounts.

## Code Explanation

The script begins by importing necessary libraries, loading environment variables, and initiating a Quart app and a 
SignalWire client. It also defines a class, `ActiveCall`, for managing active calls and transcriptions.

### ActiveCall Class
The `ActiveCall` class plays a crucial role in the script. Let's examine it:

```python
class ActiveCall:
    """Class to handle active calls"""

    def __init__(self, sid: str, dg_client: Deepgram):
        self.sid = sid
        self.dg_client = dg_client

    async def get_transcript(self, data: dict):
        ...

    async def connect_to_deepgram(self):
        ...
```

Here is a brief overview of the class methods and their operations:

- #### **init():** 
  The constructor method for the `ActiveCall` class. This method initializes the `sid` (session ID) and the 
  `dg_client` (Deepgram client).

- #### **get_transcript():**
  This method takes in a dictionary that contains Deepgram's response data. It then navigates this data to extract the
transcription and log it.
```python
async def get_transcript(self, data: dict):
    """Get transcript from the provided data dictionary"""
    transcript = data.get('channel', {}).get('alternatives', [{}])[0].get('transcript')
    if transcript:
        logger.info(f"{self.sid} - {transcript}")
```


- #### **connect_to_deepgram():**
  This method is responsible for establishing a connection with Deepgram's transcription service. It sends a request to 
  start live transcriptions and provides specific parameters such as encoding : `mulaw`, model : `phonecall`,
  tier : `nova`, channels : `2` and sample rate `8000` Hz. We do this because typical phone calls are encoded in mulaw,
  have a sample rate of 8000, and have 2 channels of audio. Furthermore, we set the model to phone call and the tier to
  nova to help with the accuracy of the transcriptions.
  
  The method then registers handlers for two events: `CLOSE` and `TRANSCRIPT_RECEIVED`. 
  The `CLOSE` event is logged when the connection with Deepgram is closed, and the `TRANSCRIPT_RECEIVED` event triggers 
  the `get_transcript` method to process and log the received transcript from Deepgram.

```python
async def connect_to_deepgram(self):
    """Establish a connection with Deepgram"""
    socket = await self.dg_client.transcription.live({
            'encoding': "mulaw",
            'sample_rate': 8000,
            'channels': 2,
            'model': 'phonecall',
            'tier': 'nova',
    })
    socket.registerHandler(socket.event.CLOSE, lambda _: logger.info("Connection Closed..."))
    socket.registerHandler(socket.event.TRANSCRIPT_RECEIVED, self.get_transcript)
    return socket
```

### Key Functions Explanation

- #### **inbound_call()**: 
This function manages the `/inbound` route and integrates the functionalities previously handled separately by two functions.
Initially, it converts the public URL, which is obtained from the application's configuration, from HTTP or HTTPS to a 
WebSocket (WSS) URL and appends `/media` to it. This converted URL is to be used for streaming. 

Next, it creates a `VoiceResponse` object and a `Start` object. A `Stream` object is also created with the WebSocket URL, and
it is configured to track both audio tracks. The `Stream` object is appended to the `Start` object, which is then appended 
to the `VoiceResponse` object. This sets up the call streaming. 

Following that, the function creates a `Dial` object and configures it to call the phone number specified in the 
application's configuration. This `Dial` object is then appended to the `VoiceResponse` object, making the call forwarding ready.

Finally, the function returns an XML response which contains all these configurations. In short, this function 
effectively allows incoming calls to be automatically forwarded to a specified number while simultaneously streaming the call.

```python
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
 ```

- #### **websocket_endpoint()**:
  This function handles the WebSocket endpoint. It manages the lifecycle of the WebSocket
  connection by establishing the connection, handling different events (like 'start', 'media', 'stop'), and closing the 
  connection when the session ends.

    ```python
    @app.websocket('/media')
    async def websocket_endpoint():
        """Handle media websocket endpoint"""
        ...
  
        while len(in_buffer) >= buffer_size and len(out_buffer) >= buffer_size:
            as_inbound = AudioSegment(in_buffer[:buffer_size], sample_width=1, frame_rate=8000, channels=1)
            as_outbound = AudioSegment(out_buffer[:buffer_size], sample_width=1, frame_rate=8000, channels=1)
            mixed = AudioSegment.from_mono_audiosegments(as_inbound, as_outbound)
            deepgram_socket.send(mixed.raw_data)

            in_buffer = in_buffer[buffer_size:]
            out_buffer = out_buffer[buffer_size:]
        ...
    ```
    This code snippet from inside the `websocket_endpoint()` function takes care of handling audio data buffering and 
    streaming. It continuously checks whether the inbound (`in_buffer`) and outbound (`out_buffer`) audio data buffers 
    have reached the specified buffer size.

    If they have, the code takes the following steps:
    
    - Create `AudioSegment` objects for the inbound and outbound audio buffers, specifying the sample width, frame rate,
      and number of channels for the audio. The audio data is expected to be mono (1 channel) with a sample width of 1 
      byte and a frame rate of 8000 Hz, which are common settings for telephony audio.
    - Mix the inbound and outbound `AudioSegment` objects into a single stereo `AudioSegment` (where one audio channel 
      corresponds to the inbound audio and the other corresponds to the outbound audio). This is done using the 
      `from_mono_audiosegments()` method.
    - Send the raw audio data of the mixed audio to the Deepgram WebSocket for transcription using `deepgram_socket.send()`.
    
    Finally, the code clears the portion of the audio data buffers that was just processed, moving the unprocessed audio
    data to the beginning of the buffers. This is done by using slicing to discard the first `buffer_size` bytes of each buffer.

- #### **start_ngrok()**: 
  This function starts an ngrok tunnel which allows the app to receive external HTTP requests, which
  is necessary for the SignalWire Webhook to reach your app. It also updates the voice URL of your SignalWire phone number
  to point to the ngrok URL.

  ```python
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
  ```

## Running the Script

To run the script, use the following command:


```commandline
python main.py
```

On receiving an inbound call, the script will automatically forward the call, stream the audio, transcribe the conversation using Deepgram, and log the transcription results.

Remember to always keep your SignalWire and Deepgram credentials secure and do not expose them in public repositories or shared code.
