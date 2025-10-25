

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

### 1️⃣ Verify Number (Happy Path) → `verify_driver_number`

**User:**  
> “Namaste, main 9876543210 se driver hoon, 2 ghante se online hoon par ride nahi mil rahi.”

**Agent should:**  
- Ask: “Registered number?”  
- On confirmation → call the tool  
- Respond:  
  > “Number blocked nahi hai… location badal kar check kijiye.”

---

### 2️⃣ Blocked Number (Simple Path) → `verify_driver_number` *(no more tools)*

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

### 4️⃣ Supply/Demand Advice → `get_supply_demand_snapshot` (+ optional `get_incentives_today`)

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


