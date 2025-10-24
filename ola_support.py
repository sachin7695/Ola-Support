import argparse
import asyncio
import os
from datetime import datetime
import math
import calendar
from typing import Dict
from typing import Optional, List
from dotenv import load_dotenv
from loguru import logger
import os
from datetime import date 
import argparse
import asyncio
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.services.groq.stt import GroqSTTService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.openai.tts import OpenAITTSService
from pipecat.pipeline.runner import PipelineRunner
from pipecat.frames.frames import TTSSpeakFrame, CancelFrame
from pipecat.processors.transcript_processor import TranscriptProcessor
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.network.small_webrtc import SmallWebRTCTransport
from pipecat.transports.network.webrtc_connection import SmallWebRTCConnection
from pipecat.audio.filters.noisereduce_filter import NoisereduceFilter
from pipecat.services.openai.stt import OpenAISTTService
from pipecat.services.openai_realtime_beta import (
    InputAudioNoiseReduction,
    InputAudioTranscription,
    OpenAIRealtimeBetaLLMService,
    SemanticTurnDetection,
    SessionProperties,
)
from tools_ola import register_ola_tools
from transcript import TranscriptHandler
load_dotenv(override=True)


def load_instrcutions(path:str):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

instruction_path = os.path.join(os.path.dirname(__file__), "info.txt")
instruction_text = load_instrcutions(instruction_path)



async def run_bot(webrtc_connection: SmallWebRTCConnection, _: argparse.Namespace):
    logger.info(f"Starting bot")
    CALL_TIMEOUT_SECS = 120  # 4 minutes
    transport = SmallWebRTCTransport(
        webrtc_connection=webrtc_connection,
        params=TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_in_filter = NoisereduceFilter(),
            vad_analyzer=SileroVADAnalyzer(params=VADParams(
                        start_secs=0.20,   # react ~100 ms after speech onset
                        confidence=0.5,
                        stop_secs=0.4,
                        min_volume=0.6,
                    )),
        ),
    )
    


    session_properties = SessionProperties(
        input_audio_transcription=InputAudioTranscription(),
        # Set openai TurnDetection parameters. Not setting this at all will turn it
        # on by default
        turn_detection=SemanticTurnDetection(),
        # Or set to False to disable openai turn detection and use transport VAD
        # turn_detection=False,
        input_audio_noise_reduction=InputAudioNoiseReduction(type="near_field"),
        # tools=tools,
        instructions=f"{instruction_text}"
    )

    # Update STT to be more language-agnostic initially
    # stt = GroqSTTService(
    #     model="whisper-large-v3-turbo",
    #     api_key=os.getenv("GROQ_API_KEY"),
    #     language=Language.HI,  # Keep Hindi as base
    #     # prompt="Detect and transcribe in the original language spoken. Common terms: EMI, loan, payment, due, credit score, CIBIL, settlement. If Hindi/Hinglish, use Devanagari script. If English, use English script."
    # )

    
    api_key = os.getenv("OPENAI_API_KEY")

    stt = OpenAISTTService(
        api_key=api_key,
        model="gpt-4o-transcribe",
        prompt=(
            "Detect and transcribe in the original language spoken. "
            "Context: Ola driver support—common terms include rides, online, booking, pickup, drop, city/locality names. "
            "If Hindi/Hinglish, use Devanagari; if English, use English script."
        ),
    )


    # voice = "shimmer" if datetime.now().hour < 18 else "echo"
    tts = OpenAITTSService(api_key=api_key, voice="coral", model = "gpt-4o-mini-tts")


    # llm = OpenAILLMService(
    #     model = "gpt-4.1",
    #     api_key=api_key,
    #     temperature = 0.7
    # )


    llm = OpenAIRealtimeBetaLLMService(
        api_key=api_key,
        session_properties=session_properties,
        start_audio_paused=False,
    )

    tools = ToolsSchema(standard_tools=[
        verify_driver_number_schema, 
    ])

    #Transcript handling to log the transcript file
    transcript = TranscriptProcessor()
    session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    transcript_handler = TranscriptHandler(output_file=f"transcripts/session_ola_{session_id}_{date.today()}.txt")

    messages = [
        {
            "role": "user",
            "content": "say hello"
            
        }
    ]
    # Register Ola tools (one-liner)
    tools = register_ola_tools(llm)


    context = OpenAILLMContext(messages, tools)
    context_aggregator = llm.create_context_aggregator(context)

    pipeline = Pipeline(
        [
            transport.input(),  
            # stt,
            # transcript.user(),
            context_aggregator.user(),
            llm,  
            transcript.user(),
            # tts,
            transport.output(),  
            transcript.assistant(),
            context_aggregator.assistant(),
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            allow_interruptions=True,
            enable_metrics=True,
            enable_usage_metrics=True,
            report_only_initial_ttfb=True,
        ),
    )



    # llm.register_function(
    #     "verify_driver_number",
    #     make_verify_driver_number()
    # )


    async def stop_session():
        logger.info(f"Stopping session in room")

        try:
            # Queue a cancel frame to stop the pipeline
            await asyncio.sleep(CALL_TIMEOUT_SECS)
            logger.info("Auto-ending call after 2 minutes")
            await task.queue_frame(TTSSpeakFrame("Thank you for your time. This call will now end."))
            await task.queue_frame(CancelFrame())
            # Cancel the task
            await task.cancel()
        except Exception as e:
            logger.error(f"Error stopping session: {e}")



    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info(f"Client csageonnected")


        first_turn = {
            "role": "system",
            "content": (
                "### FIRST_TURN (Ola Driver Support)\n"
                "- If caller complains about not getting rides, greet and ask: 'Kya yeh aapka registered number hai?'\n"
                "- When the caller provides or confirms the number, CALL tool `verify_driver_number` "
                "with the exact number they said. Wait for the tool result and proceed:\n"
                "  * registered & not blocked -> 'Aapka number blocked nahi hai. Sab theek hai.' + suggestion\n"
                "  * registered & blocked     -> inform blocked + offer human handover\n"
                "  * not registered           -> ask for registered number (max 2 tries) then offer handover\n"
                "- Keep replies short, in Hindi/Hinglish, one question at a time.\n"
                "- Do NOT mention loans/EMI/IDs or internal tools.\n"
            )
        }


        context.messages.append(first_turn)
        await task.queue_frames([context_aggregator.user().get_context_frame()])
        asyncio.create_task(stop_session())

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info(f"Client disconnected")

    @transcript.event_handler("on_transcript_update")
    async def on_transcript_update(processor, frame):
        await transcript_handler.on_transcript_update(processor, frame)

    await PipelineRunner(handle_sigint=False).run(task)



if __name__ == "__main__":
    from run import main
    main()
