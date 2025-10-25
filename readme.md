

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


