Fresh Install Guide
This has currently been tested on:
Raspberry Pi OS Lite, 32-bit
Raspberry Pi Zero
32 GB microSD card
Start with a fresh Raspberry Pi OS Lite installation, then sign in to the Pi through SSH.
1. Confirm you are connected to the correct Pi
Copy and paste:
hostname
whoami
cat /etc/os-release | grep PRETTY_NAME
Make sure the hostname and username match the Pi you intended to connect to.
2. Update the package list and install Git
sudo apt update
sudo apt install -y git
Let that finish completely before continuing.
3. Download Cellar-pi
cd ~
git clone https://github.com/know4you/Cellar-pi.git
cd Cellar-pi
Make sure the files downloaded:
ls -la
You should see files similar to:
README.md
cellar_logger.py
install.sh
requirements.txt
setup.sh
4. Run a quick sanity check
Before running the installer, check the scripts for obvious syntax problems:
bash -n install.sh
bash -n setup.sh
python3 -m py_compile cellar_logger.py
No output is good. It means the scripts passed their basic syntax checks.
5. Install Cellar-pi
sudo bash install.sh
The installer should not take too long, hopefully.
At some points it may look like it has frozen. I know—it looks scary. Give it a minute or ten before assuming something went wrong. Package installation on a Pi Zero can be slow, but it should start moving again.
6. Open User Control
After installation finishes, run:
/uc
/uc stands for User Control.
You can use it to:
View sensor readings
Change sensor settings
Configure notifications
Schedule the daily report
Check system status
Troubleshoot the logger
I think you’ll love it. I’ve tried to make the entire project stupid easy to install, configure, and use.
Thank You
Thank you for installing Project Cellar-pi.
This project started because I wanted to move my homelab into my cellar. It was making my bedroom way too hot. What started as a simple temperature monitor slowly turned into this.
Maybe someday, if the project takes off, I’ll add a coffee link. I don’t know yet.
For now, I genuinely hope someone enjoys using it. I’ve tried my hardest to make it simple enough that nearly anyone can get it running.
