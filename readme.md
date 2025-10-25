

### A simple guide to set up and run the **Ola Driver Support** assistant locally.

---

##  Setup Instructions for Linux

### 1. Install Python 3.12.x
Make sure Python 3.12 or higher is installed:

```bash 
step-1 python --version
Step-2 pip install virtualenv
Step-3 mkdir env
       cd env
Step-4 python -m virtualenv pc_env
       source env/pc_env/bin/activate
       cd ..
Step-5 git clone https://github.com/sachin7695/Ola-Support.git
       cd Ola-Support
Step-6 pip install -r requirements.txt
```

### 2. Running the Script
```bash
Step-1 cp .env.example .env and put your api key in the .env file
Step-2 python ola_support.py
```


---

## 🎙️ Driver Support — Test Dialogues

> Speak or type the dialogues below **in order per scenario** to test your Ola Driver Support flow.
>  
> Each scenario triggers a specific function/tool chain.

---

### 1️⃣ Verify Number → `verify_driver_number`

**User:**  
> “Namaste, main Ramesh,  driver hoon, 2 ghante se online hoon par ride nahi mil rahi.”

**Agent should:**  
- Ask: “Registered number?”  
- On confirmation → call the tool  
- Respond:  
  > “Number blocked nahi hai… location badal kar check kijiye.”

---

### 2️⃣ Blocked Number → `verify_driver_number` *(no more tools)*

**User:**  
> “Mera number 9911223344 hai, rides nahi aati.”

**Agent should:**  
- After tool result (blocked):  
  > “Aapka number abhi block par hai. Ek human agent aapka account unblock karne mein madad karega.”  
  *(End politely.)*

---

### 3️⃣ App Outdated → `check_app_online_status` → `push_device_reauth`

**User:**  
> “Main 9876543210, app open ho raha hai par booking nahi aa rahi.”

**Agent should:**  
- Verify number → check app status  
- If `needs_update == true`:  
  > “App ka version purana lag raha hai, update link bhej raha hoon.”  
  *(Triggers `push_device_reauth(purpose="update")`.)*

---

### 4️⃣ Supply/Demand Advice → `get_supply_demand_snapshot` 

**User:**  
> “Main Majestic Bus Stand ke paas hoon, 2 ghante se online hoon par ride nahi.”

**Agent should:**  
- Ask/assume GPS or use known lat/lon for test → call snapshot  
- Reply:  
  > “Is area mein demand kam hai… Peenya taraf move kariye; aaj wahan demand zyada hai.”  
- *(Optional)*:  
  > “Aaj Bengaluru mein 3 rides → ₹150 quest chal raha hai.”

---

### 5️⃣ Wallet/Payout Hold → `fetch_wallet_and_payouts`

**User:**  
> “Mera payout hold pe hai, 9876543210.”

**Agent should:**  
- Verify (or use cached number) → fetch wallet/payouts  
- If holds present (e.g. “KYC hold”):  
  > “KYC ke wajah se payout hold par hai. Kripya KYC complete kijiye.”

---

### 6️⃣ Quick Re-auth (OTP Resend) → `push_device_reauth`

**User:**  
> “Login baar-baar fail ho raha hai, OTP nahi aa raha.”

**Agent should:**  
> “OTP bhej diya gaya hai—dubara login karke try kijiye.”  
*(Triggers `push_device_reauth(purpose="reauth")`.)*

---

### 7️⃣ Incentive Check → `get_incentives_today`

**User:**  
> “Delhi mein aaj koi incentive ya surge chal raha hai?”

**Agent should:**  
- Call `get_incentives_today()`  
- Respond:  
  > “Delhi mein surge 1.4x dikh raha hai, quest slots abhi available nahi.”

---

## 🎬 Demo Google Drive Link

[Watch Demo](https://drive.google.com/file/d/1_PtCqYCoeDFtw10C9GWs3afMJM0JDmfj/view?usp=sharing)

## Archictecture flow 

---
## 📄 File Structure

```
Ola-Support/
├── ola_support.py          # Main bot pipeline
├── run.py                  # FastAPI server
├── tool_calling.py         # Function schemas & implementations
├── transcript.py           # Transcript handler
├── prompt.txt              # System instructions
├── requirements.txt        # Python dependencies
├── .env.example            # Environment template
├── .gitignore              # Git ignore rules
├── readme.md               # Test scenarios guide
└── transcripts/            # Session logs
    └── session_ola_*.txt

┌─────────────────────────────────────────────────────────────────────────┐
│                         CLIENT (Web Browser)                            │
│                         SmallWebRTC Prebuilt UI                         │
└────────────────────────────┬────────────────────────────────────────────┘
                             │ WebRTC (Audio Stream)
                             ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                      FASTAPI SERVER (run.py)                            │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  WebRTC Connection Manager                                       │   │
│  │  - Ice Servers (STUN)                                           │   │
│  │  - SDP Offer/Answer Exchange                                    │   │
│  │  - Connection State Management                                  │   │
│  └──────────────────────────────────────────────────────────────────┘   │
└────────────────────────────┬────────────────────────────────────────────┘
                             │
                             ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                    PIPECAT PIPELINE (ola_support.py)                    │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  1. AUDIO INPUT PROCESSING                                      │   │
│  │     ├── SmallWebRTCTransport (Input)                           │   │
│  │     ├── NoisereduceFilter                                       │   │
│  │     └── SileroVADAnalyzer                                       │   │
│  │         └── VADParams (start: 0.2s, confidence: 0.5)           │   │
│  └─────────────────────────────────────────────────────────────────┘   │   │
│                             ↓                                           │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  3. CONTEXT AGGREGATION                                         │   │
│  │     ├── OpenAILLMContext                                        │   │
│  │     │   ├── Messages History                                    │   │
│  │     │   └── Tools Schema                                        │   │
│  │     └── Context Aggregator (User/Assistant)                    │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                             ↓                                           │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  4. LLM PROCESSING                                              │   │
│  │     └── OpenAIRealtimeBetaLLMService                           │   │
│  │         ├── Session Properties                                  │   │
│  │         │   ├── Input Audio Transcription                       │   │
│  │         │   ├── Semantic Turn Detection                         │   │
│  │         │   ├── Noise Reduction (near_field)                    │   │
│  │         │   └── System Instructions (prompt.txt)                │   │
│  │         └── Tool Calling Integration                            │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                             ↓                                           │
  
│                                                                        │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  6. AUDIO OUTPUT                                                │   │
│  │     └── SmallWebRTCTransport (Output)                          │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                             ↓                                           │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  7. TRANSCRIPT LOGGING                                          │   │
│  │     └── TranscriptProcessor                                     │   │
│  │         └── TranscriptHandler                                   │   │
│  │             └── Output: transcripts/session_*.txt               │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
                             │
                             ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                    TOOL CALLING SYSTEM (tool_calling.py)                │
│                                                                         │
│  ┌──────────────────────┬──────────────────────┬───────────────────┐   │
│  │ Driver Verification  │ Account Health       │ Ride Support      │   │
│  ├──────────────────────┼──────────────────────┼───────────────────┤   │
│  │ • verify_driver_     │ • get_driver_        │ • check_app_      │   │
│  │   number             │   account_health     │   online_status   │   │
│  │                      │                      │ • get_supply_     │   │
│  │ Cache: Last verified │ Check:               │   demand_snapshot │   │
│  │ MSISDN               │ - docs_pending       │                   │   │
│  │                      │ - bgv_status         │ Returns:          │   │
│  │ Returns:             │ - strikes            │ - demand_index    │   │
│  │ - is_registered      │ - deactivation_      │ - median_wait     │   │
│  │ - is_blocked         │   reason             │ - hotspots        │   │
│  │ - city               │                      │ - suggestions     │   │
│  │ - display_name       │                      │                   │   │
│  │ - rating             │                      │                   │   │
│  └──────────────────────┴──────────────────────┴───────────────────┘   │
│                                                                         │
│  ┌──────────────────────┬──────────────────────┬───────────────────┐   │
│  │ Wallet & Payouts     │ Incentives           │ Device Auth       │   │
│  ├──────────────────────┼──────────────────────┼───────────────────┤   │
│  │ • fetch_wallet_and_  │ • get_incentives_    │ • push_device_    │   │
│  │   payouts            │   today              │   reauth          │   │
│  │                      │                      │                   │   │
│  │ Returns:             │ Input:               │ Purposes:         │   │
│  │ - wallet_balance     │ - city               │ - reauth (OTP)    │   │
│  │ - next_payout_date   │ - date (YYYY-MM-DD)  │ - update (app)    │   │
│  │ - holds[]            │                      │ - docs_update     │   │
│  │                      │ Returns:             │   (RC/KYC)        │   │
│  │                      │ - surge_multiplier   │                   │   │
│  │                      │ - quest_bonus        │ Returns:          │   │
│  │                      │ - slots_remaining    │ - sent status     │   │
│  │                      │                      │ - token_hint      │   │
│  └──────────────────────┴──────────────────────┴───────────────────┘   │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │ Support Ticket Creation                                          │   │
│  ├──────────────────────────────────────────────────────────────────┤   │
│  │ • create_support_ticket                                          │   │
│  │                                                                  │   │
│  │ Categories:                                                      │   │
│  │ - account_block                                                  │   │
│  │ - docs_pending                                                   │   │
│  │ - payout_hold                                                    │   │
│  │ - app_issue                                                      │   │
│  │ - other                                                          │   │
│  │                                                                  │   │
│  │ Returns: ticket_id (e.g., OLA-1234567)                          │   │
│  └──────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
                             │
                             ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                        MOCK DATA STORES                                 │
│                                                                         │
│  DRIVERS_DB          ACCOUNT_HEALTH_DB       ONLINE_STATUS_DB          │
│  WALLET_DB           INCENTIVES_DB           [In-Memory Mock]          │
└─────────────────────────────────────────────────────────────────────────┘
