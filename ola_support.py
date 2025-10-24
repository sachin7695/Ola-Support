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
from typing import Set
import json
from fastapi import WebSocket
from collections import deque
import numpy as np
import os
from datetime import date 
import argparse
import asyncio
from pipecat.transports.network.fastapi_websocket import FastAPIWebsocketParams
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.services.llm_service import FunctionCallParams
from pipecat.services.groq.stt import GroqSTTService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.openai.tts import OpenAITTSService
from pipecat.frames.frames import TranscriptionMessage, TranscriptionUpdateFrame
from pipecat.pipeline.runner import PipelineRunner
from pipecat.frames.frames import TranscriptionMessage, TTSSpeakFrame, CancelFrame
from pipecat.processors.transcript_processor import TranscriptProcessor
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.network.small_webrtc import SmallWebRTCTransport
from pipecat.transports.network.webrtc_connection import SmallWebRTCConnection
from pipecat.transcriptions.language import Language
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
load_dotenv(override=True)


def load_instrcutions(path:str):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

instruction_path = os.path.join(os.path.dirname(__file__), "info.txt")
instruction_text = load_instrcutions(instruction_path)


class BorrowerRepo:
    """Very simple JSON-backed repo. Switch to SQLite/Redis later without touching the rest of code."""
    def __init__(self, path: str):
        self._path = path
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                self._db = json.load(f)
        else:
            self._db = {}

    async def get_by_id(self, borrower_id: str) -> Optional[dict]:
        # Simulate I/O (and yield control)
        await asyncio.sleep(0)
        return self._db.get(borrower_id)

# Init the repo
current_dir = os.getcwd()
path=os.path.join(current_dir, "borrowers.json")
BORROWER_REPO = BorrowerRepo(path = path)


BORROWER_STORE: Dict[str, dict] = {}
def natural_amount_phrase(amount: int, lang_hint: str = "hinglish") -> str:
    # super simple rules that sound natural enough
    # tweak buckets as you like
    if 900 <= amount < 1500:
        return "lagbhag hazaar" if lang_hint=="hinglish" else "around one thousand"
    if 1500 <= amount < 2500:
        return "dhai hazaar ke aas-paas" if lang_hint=="hinglish" else "around two thousand, maybe twenty-five hundred"
    if 2500 <= amount < 3500:
        return "karib teen hazaar" if lang_hint=="hinglish" else "around three thousand"
    if 3500 <= amount < 5500:
        return "saade chaar hazaar" if lang_hint=="hinglish" else "around forty-five hundred"
    if 5500 <= amount < 7500:
        return "saade paanch hazaar" if lang_hint=="hinglish" else "around fifty-five hundred"
    # fallback
    return f"karib {round(amount/1000)*1000} rupees" if lang_hint=="hinglish" else f"around {round(amount/1000)*1000} rupees"

def natural_date_phrase(iso_date: str, lang_hint: str = "hinglish") -> str:
    # "2025-08-05" -> "5 August" or "August 5th"
    dt = datetime.strptime(iso_date, "%Y-%m-%d")
    if lang_hint == "hinglish":
        return f"{dt.day} August" if dt.month == 8 else f"{dt.day} {calendar.month_name[dt.month]}"
    else:
        # English with ordinal
        day = dt.day
        suffix = "th" if 11<=day<=13 else {1:"st",2:"nd",3:"rd"}.get(day%10, "th")
        return f"{calendar.month_name[dt.month]} {day}{suffix}"

def make_save_promise_to_pay(borrower_store: Dict[str, dict]):
    async def save_promise_to_pay(params: FunctionCallParams):
        borrower_id = params.arguments["borrower_id"]
        ctx = borrower_store.get(borrower_id)

        if not ctx:
            # No borrower loaded for this ID; fail safely
            await params.result_callback({"status": "error", "reason": "unknown_borrower"})
            return

        amount_due = int(ctx["amount_due"])  # authoritative value from server context
        promised_amount = int(params.arguments["ptp_amount"])
        ptp_date = params.arguments["ptp_date"]
        delay_reason = params.arguments.get("delay_reason", "")
        negotiation_result = params.arguments.get("negotiation_result", "")

        # business rule: only accept if >= ₹900 (or add your % threshold internally)
        if promised_amount < 900:
            await params.result_callback({"status": "rejected", "reason": "amount_below_min"})
            return

        # save
        os.makedirs("ptp_logs", exist_ok=True)
        record = {
            "borrower_id": borrower_id,
            "loan_account_id": ctx.get("loan_account_id"),
            "ptp_date": ptp_date,
            "ptp_amount": promised_amount,
            "delay_reason": delay_reason,
            "negotiation_result": negotiation_result,
            "amount_due_at_ptp": amount_due,
        }
        with open(f"ptp_logs/{borrower_id}_{ptp_date}.txt", "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2)

        await params.result_callback({"status": "saved"})
    return save_promise_to_pay

def make_load_borrower_context(repo: BorrowerRepo,
                               borrower_store: Dict[str, dict],
                               context: OpenAILLMContext,
                               context_aggregator,
                               task: PipelineTask):

    async def load_borrower_context(params: FunctionCallParams):
        borrower_id = params.arguments["borrower_id"].strip()
        rec = await repo.get_by_id(borrower_id)

        if not rec:
            # speak a brief clarification and return not_found
            await params.result_callback({"status": "not_found"})
            return

        # Build humanized phrases
        amount_phrase_hi = natural_amount_phrase(int(rec["amount_due"]), "hinglish")
        amount_phrase_en = natural_amount_phrase(int(rec["amount_due"]), "english")
        due_date_hi      = natural_date_phrase(rec["emi_due_date"], "hinglish")
        due_date_en      = natural_date_phrase(rec["emi_due_date"], "english")

        # Save server-side store for other tools (e.g., PTP)
        borrower_store[borrower_id] = rec

        # Compose hidden system context
        extra_message = {
            "role": "system",
            "content": (
                "### BORROWER_CONTEXT (do not read aloud)\n"
                f"BorrowerName: {rec['borrower_name']}\n"
                f"LoanType: {rec['loan_type']}\n"
                f"AmountDueRaw: {rec['amount_due']}\n"
                f"AmountPhraseHinglish: {amount_phrase_hi}\n"
                f"AmountPhraseEnglish: {amount_phrase_en}\n"
                f"DueDateISO: {rec['emi_due_date']}\n"
                f"DueDateHinglish: {due_date_hi}\n"
                f"DueDateEnglish: {due_date_en}\n"
                f"BorrowerID: {rec['borrower_id']}\n"
                f"AccountID: {rec['loan_account_id']}\n"
                "\n"
                "### WHEN EXPLAINING DUE\n"
                "- If Hinglish, use AmountPhraseHinglish and DueDateHinglish\n"
                "- If English,  use AmountPhraseEnglish and  DueDateEnglish\n"
                "- Do not say exact rupees or ISO dates.\n"
            )
        }

        # Inject it into the model’s context live
        context.messages.append(extra_message)
        # await task.queue_frames([context_aggregator.user().get_context_frame()])

        await params.result_callback({"status": "loaded", "borrower_id": borrower_id})

    return load_borrower_context







# Simple in-memory repo (or swap to DB later)
DRIVERS_DB = {
    "+919876543210": {"name": "Ramesh", "blocked": False, "registered": True},
    "+919911223344": {"name": "Suresh", "blocked": True,  "registered": True},
    # Add more test entries...
}

def normalize_msisdn(raw: str, default_cc: str = "+91") -> str:
    # Keep digits only, then prefix with +91 if 10 digits
    digits = "".join(ch for ch in raw if ch.isdigit())
    if digits.startswith("91") and len(digits) == 12:
        return f"+{digits}"
    if len(digits) == 10:
        return f"{default_cc}{digits}"
    # Fallback: try to add '+' if a country code seems present
    return f"+{digits}" if not raw.startswith("+") else raw

def make_verify_driver_number():
    async def verify_driver_number(params: FunctionCallParams):
        raw = params.arguments["phone_number"]
        cc  = params.arguments.get("country_code", "+91")
        msisdn = normalize_msisdn(raw, cc)

        rec = DRIVERS_DB.get(msisdn)
        result = {
            "normalized_number": msisdn,
            "is_registered": bool(rec and rec.get("registered", False)),
            "is_blocked": bool(rec and rec.get("blocked", False)),
            "display_name": rec.get("name") if rec else None,
        }
        await params.result_callback(result)
    return verify_driver_number


# Put near your other FunctionSchema definitions
verify_driver_number_schema = FunctionSchema(
    name="verify_driver_number",
    description=(
        "Verify the driver's phone number. "
        "Use this immediately after the user provides or confirms their registered number. "
        "Returns whether the number is registered and if it is blocked."
    ),
    properties={
        "phone_number": {
            "type": "string",
            "description": "Raw phone number as the user spoke it (e.g., '9876543210', '+91 98765 43210')."
        },
        "country_code": {
            "type": "string",
            "description": "Optional ISO country prefix, default '+91' for India.",
            "default": "+91"
        }
    },
    required=["phone_number"]
)





class TranscriptHandler:
    """Handles real-time transcript processing and output.

    Maintains a list of conversation messages and outputs them either to a log
    or to a file as they are received. Each message includes its timestamp and role.

    Attributes:
        messages: List of all processed transcript messages
        output_file: Optional path to file where transcript is saved. If None, outputs to log only.
    """

    def __init__(self, output_file: Optional[str] = None):
        """Initialize handler with optional file output.

        Args:
            output_file: Path to output file. If None, outputs to log only.
        """
        self.messages: List[TranscriptionMessage] = []
        self.output_file: Optional[str] = output_file
        logger.debug(
            f"TranscriptHandler initialized {'with output_file=' + output_file if output_file else 'with log output only'}"
        )

    async def save_message(self, message: TranscriptionMessage):
        """Save a single transcript message.

        Outputs the message to the log and optionally to a file.

        Args:
            message: The message to save
        """
        timestamp = f"[{message.timestamp}] " if message.timestamp else ""
        line = f"{timestamp}{message.role}: {message.content}"

        # Always log the message
        logger.info(f"Transcript: {line}")

        if self.output_file:
            os.makedirs(os.path.dirname(self.output_file), exist_ok=True)
        # Optionally write to file
        if self.output_file:
            try:
                with open(self.output_file, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except Exception as e:
                logger.error(f"Error saving transcript message to file: {e}")

    async def on_transcript_update(
        self, processor: TranscriptProcessor, frame: TranscriptionUpdateFrame
    ):
        """Handle new transcript messages.

        Args:
            processor: The TranscriptProcessor that emitted the update
            frame: TranscriptionUpdateFrame containing new messages
        """
        logger.debug(f"Received transcript update with {len(frame.messages)} new messages")

        for msg in frame.messages:
            self.messages.append(msg)
            await self.save_message(msg)

async def run_bot(webrtc_connection: SmallWebRTCConnection, _: argparse.Namespace):
    logger.info(f"Starting bot")
    CALL_TIMEOUT_SECS = 240  # 4 minutes
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

    def get_greeting():
        hour = datetime.now().hour
        if hour < 12:
            return "Good morning"
        elif hour < 17:
            return "Good afternoon"
        else:
            return "Good evening"



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
        # for msg in frame.messages:
        #     if isinstance(msg, TranscriptionMessage):
        #         timestamp = f"[{msg.timestamp}] " if msg.timestamp else ""
        #         line = f"{timestamp}{msg.role}: {msg.content}"
        #         logger.info(f"Transcript: {line}")
        await transcript_handler.on_transcript_update(processor, frame)

    await PipelineRunner(handle_sigint=False).run(task)



if __name__ == "__main__":
    from run import main
    main()
