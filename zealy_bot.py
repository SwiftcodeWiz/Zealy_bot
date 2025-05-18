import hashlib
import asyncio
import re
import shutil
import time
import os
import traceback
import sys
from datetime import datetime
import platform

# First check if required packages are installed
try:
    import psutil
    from dotenv import load_dotenv
    import chromedriver_autoinstaller
    import concurrent.futures
    from telegram import Update
    from telegram.ext import (
        Application,
        CommandHandler,
        ContextTypes,
        ApplicationHandlerStop,
        MessageHandler,
        filters
    )
    from telegram.error import TelegramError, NetworkError
    from selenium.webdriver.chrome.service import Service as ChromeService
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import (
        StaleElementReferenceException,
        WebDriverException,
        TimeoutException
    )
    from selenium.webdriver.chrome.service import Service
except ImportError as e:
    print(f"ERROR: Missing required package: {str(e)}")
    print("Please install required packages using:")
    print("pip install python-telegram-bot selenium python-dotenv psutil chromedriver-autoinstaller")
    input("Press Enter to exit...")
    sys.exit(1)

# Try to load .env file
print("Loading environment variables...")
load_dotenv()

# Check if env variables exist
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
CHAT_ID_STR = os.getenv('CHAT_ID')

if not TELEGRAM_BOT_TOKEN:
    print("ERROR: TELEGRAM_BOT_TOKEN environment variable is missing!")
    print("Create a .env file in the same directory with:")
    print("TELEGRAM_BOT_TOKEN=your_telegram_bot_token")
    print("CHAT_ID=your_chat_id")
    input("Press Enter to exit...")
    sys.exit(1)

if not CHAT_ID_STR:
    print("ERROR: CHAT_ID environment variable is missing!")
    print("Create a .env file in the same directory with:")
    print("CHAT_ID=your_chat_id (must be a number)")
    input("Press Enter to exit...")
    sys.exit(1)

try:
    CHAT_ID = int(CHAT_ID_STR)
except ValueError:
    print(f"ERROR: CHAT_ID must be an integer, got: {CHAT_ID_STR}")
    input("Press Enter to exit...")
    sys.exit(1)

# Automatic chromedriver installation
print("Setting up ChromeDriver...")
try:
    chromedriver_autoinstaller.install()
    print("ChromeDriver installed successfully")
except Exception as e:
    print(f"Warning: ChromeDriver auto-installation failed: {e}")
    print("We'll try to use existing Chrome/ChromeDriver")

# Configuration
CHECK_INTERVAL = 120
MAX_URLS = 10
ZEALY_CONTAINER_SELECTOR = "div.flex.flex-col.w-full.pt-100"
REQUEST_TIMEOUT = 20

# Set appropriate paths based on environment
IS_RENDER = os.getenv('IS_RENDER', 'false').lower() == 'true'

if IS_RENDER:
    # Render.com specific paths
    CHROME_PATH = '/usr/bin/chromium'  # Render uses Chrome, not Chromium
    CHROMEDRIVER_PATH = '/usr/bin/chromedriver'
elif platform.system() == "Windows":
    # Default Windows paths
    CHROME_PATH = os.getenv('CHROME_BIN', 
                          r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    
    CHROMEDRIVER_PATH = os.getenv('CHROME_DRIVER', 
                                shutil.which('chromedriver') or r"C:\Program Files\chromedriver\chromedriver.exe")
else:
    # Linux/Docker paths
    CHROME_PATH = os.getenv('CHROME_BIN', '/usr/bin/chromium')
    CHROMEDRIVER_PATH = os.getenv('CHROME_DRIVER', '/usr/lib/chromium/chromedriver')

# Global storage
monitored_urls = {}
is_monitoring = False
SECURITY_LOG = "activity.log"

def kill_previous_instances():
    current_pid = os.getpid()
    try:
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                if 'python' in proc.info['name'].lower():
                    cmdline = ' '.join(proc.info['cmdline'])
                    if 'zealy_bot.py' in cmdline and proc.info['pid'] != current_pid:
                        print(f"🚨 Killing previous instance (PID: {proc.info['pid']})")
                        proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                continue
    except Exception as e:
        print(f"Warning: Error checking previous instances: {e}")

def get_chrome_options():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-features=VizDisplayCompositor")
    
    # Add special options for Render.com
    if IS_RENDER:
        options.add_argument("--disable-setuid-sandbox")
        options.add_argument("--disable-dev-tools")
        options.add_argument("--no-zygote")
        options.add_argument("--single-process")
        options.add_argument("--disable-extensions")
    
    # Use environment variables for paths
    print(f"🕵️ Using Chrome binary path: {CHROME_PATH}")
    print(f"🕵️ Using Chromedriver path: {CHROMEDRIVER_PATH}")
    
    # Check if we're in local development and paths should exist
    if not IS_RENDER:
        if not os.path.exists(CHROME_PATH):
            print(f"⚠️ WARNING: Chrome not found at expected path: {CHROME_PATH}")
            # Try to locate Chrome/Chromium
            if platform.system() == "Windows":
                possible_paths = [
                    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
                ]
                for path in possible_paths:
                    if os.path.exists(path):
                        print(f"✅ Found Chrome at: {path}")
                        options.binary_location = path
                        break
        else:
            options.binary_location = CHROME_PATH
    else:
        # On Render, we trust the paths exist
        options.binary_location = CHROME_PATH
        
    return options

def get_content_hash(url):
    driver = None
    try:
        print(f"🌐 Initializing driver for URL: {url}")
        options = get_chrome_options()
        
        try:
            if IS_RENDER or not os.path.exists(CHROMEDRIVER_PATH):
                # On Render or if we can't find chromedriver, let Selenium find it automatically
                print("Using default ChromeDriver (auto-detection)")
                driver = webdriver.Chrome(options=options)
            else:
                # Use specified path when available
                print(f"Using specified ChromeDriver path: {CHROMEDRIVER_PATH}")
                service = Service(executable_path=CHROMEDRIVER_PATH)
                driver = webdriver.Chrome(service=service, options=options)
                
            print(f"🌐 Loading URL: {url}")
            driver.get(url)
            
            print("⏳ Waiting for page elements...")
            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ZEALY_CONTAINER_SELECTOR))
            )
            
            container = driver.find_element(By.CSS_SELECTOR, ZEALY_CONTAINER_SELECTOR)
            content = container.text
            
            print(f"📄 Content retrieved, length: {len(content)} chars")
            clean_content = re.sub(
                r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z|\d+ XP|\b[A-F0-9]{8}-(?:[A-F0-9]{4}-){3}[A-F0-9]{12}\b', 
                '', 
                content
            )
            content_hash = hashlib.sha256(clean_content.strip().encode()).hexdigest()
            print(f"🔢 Hash generated: {content_hash[:8]}...")
            return content_hash
        except TimeoutException:
            print(f"⚠️ Timeout waiting for page elements on {url}")
            return None
        except WebDriverException as e:
            print(f"⚠️ WebDriver error: {str(e)}")
            return None
    except Exception as e:
        print(f"❌ Content check error: {str(e)}")
        return None
    finally:
        try:
            if driver:
                print("🧹 Closing WebDriver")
                driver.quit()
        except Exception as e:
            print(f"⚠️ Error closing WebDriver: {str(e)}")

async def auth_middleware(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != CHAT_ID:
        await update.message.reply_text("🚫 Unauthorized access!")
        raise ApplicationHandlerStop

async def send_notification(bot, message):
    retries = 0
    while retries < 3:
        try:
            await bot.send_message(chat_id=CHAT_ID, text=message)
            print(f"✅ Sent notification: {message[:50]}...")
            return True
        except (TelegramError, NetworkError) as e:
            print(f"📡 Network error: {str(e)} - Retry {retries+1}/3")
            retries += 1
            await asyncio.sleep(5)
    return False

async def check_urls(bot):
    global monitored_urls
    current_time = time.time()
    
    if not monitored_urls:
        print("⚠️ No URLs to check")
        return
        
    for url in list(monitored_urls.keys()):
        print(f"🔍 Checking URL: {url}")
        try:
            start_time = time.time()
            current_hash = get_content_hash(url)
            
            if not current_hash:
                monitored_urls[url]['failures'] += 1
                print(f"⚠️ Failed to get hash for {url} - Failure #{monitored_urls[url]['failures']}")
                if monitored_urls[url]['failures'] > 3:
                    del monitored_urls[url]
                    await send_notification(bot, f"🔴 Removed from monitoring due to repeated failures: {url}")
                    print(f"🗑️ Removed {url} after 3 failures")
                continue
                
            monitored_urls[url]['failures'] = 0
            if monitored_urls[url]['hash'] != current_hash:
                print(f"🔔 Change detected for {url}")
                if current_time - monitored_urls[url].get('last_notified', 0) > 300:
                    success = await send_notification(
                        bot, f"🚨 CHANGE DETECTED!\n{url}\nResponse time: {time.time()-start_time:.2f}s")
                    if success:
                        monitored_urls[url].update({
                            'last_notified': current_time,
                            'hash': current_hash,
                            'last_checked': current_time
                        })
                        print(f"✅ Notification sent for {url}")
                    else:
                        print(f"❌ Failed to send notification for {url}")
            else:
                print(f"✓ No changes for {url}")
            
            monitored_urls[url]['last_checked'] = current_time
        except Exception as e:
            print(f"⚠️ Error processing {url}: {str(e)}")
            
    print(f"✅ Checked {len(monitored_urls)} URLs")

# Command handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚀 Zealy Monitoring Bot\n\n"
        "Commands:\n"
        "/add <url> - Add monitoring URL\n"
        "/list - Show monitored URLs\n"
        "/run - Start monitoring\n"
        "/stop - Stop monitoring\n"
        "/purge - Remove all URLs\n"
        f"Max URLs: {MAX_URLS}"
    )

async def list_urls(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not monitored_urls:
        await update.message.reply_text("No monitored URLs")
        return
    message = ["📋 Monitored URLs:"] + [f"{idx}. {url}" for idx, url in enumerate(monitored_urls.keys(), 1)]
    await update.message.reply_text("\n".join(message)[:4000])

async def add_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != CHAT_ID:
        return
    
    if len(monitored_urls) >= MAX_URLS:
        await update.message.reply_text(f"❌ Maximum URLs limit ({MAX_URLS}) reached")
        return
        
    try:
        # Check if args exist
        if not context.args or not context.args[0]:
            await update.message.reply_text("❌ Usage: /add <zealy-url>")
            return
            
        url = context.args[0].lower()
        print(f"📥 Attempting to add URL: {url}")
        
        # Validate URL format
        if not re.match(r'^https://(www\.)?zealy\.io/cw/[\w/-]+$', url):
            await update.message.reply_text("❌ Invalid Zealy URL format")
            return
            
        # Check if already monitoring
        if url in monitored_urls:
            await update.message.reply_text("ℹ️ URL already monitored")
            return
            
        # Show processing message
        processing_msg = await update.message.reply_text("⏳ Verifying URL...")
        
        # Get initial hash in a separate thread or process
        try:
            loop = asyncio.get_event_loop()
            print(f"🔄 Getting initial hash for {url}")
            initial_hash = await loop.run_in_executor(None, get_content_hash, url)
            
            if not initial_hash:
                await processing_msg.edit_text("❌ Failed to verify URL content. Check console for details.")
                return
                
            # Add to monitored URLs
            monitored_urls[url] = {
                'hash': initial_hash,
                'last_notified': 0,
                'last_checked': time.time(),
                'failures': 0
            }
            
            print(f"✅ URL added successfully: {url}")
            await processing_msg.edit_text(
                f"✅ Added: {url}\n📊 Now monitoring: {len(monitored_urls)}/{MAX_URLS}"
            )
            
        except Exception as e:
            print(f"❌ Error while getting initial hash: {str(e)}")
            await processing_msg.edit_text(f"❌ Failed to add URL: {str(e)}")
            
    except IndexError:
        await update.message.reply_text("❌ Usage: /add <zealy-url>")
    except Exception as e:
        print(f"⚠️ Error in add_url: {str(e)}")
        await update.message.reply_text(f"❌ Internal server error: {str(e)}")

async def run_monitoring(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_monitoring
    if is_monitoring:
        await update.message.reply_text("⚠️ Already monitoring")
        return
    if not monitored_urls:
        await update.message.reply_text("❌ No URLs to monitor")
        return
    
    try:
        # Set flag first
        is_monitoring = True
        # Create monitoring task
        monitor_task = asyncio.create_task(start_monitoring(context.application))
        # Store task in context for reference
        context.chat_data['monitor_task'] = monitor_task
        await update.message.reply_text("✅ Monitoring started!")
        print("✅ Monitoring task created and started")
    except Exception as e:
        is_monitoring = False
        await update.message.reply_text(f"❌ Failed to start monitoring: {str(e)}")
        print(f"❌ Error starting monitoring: {str(e)}")

async def stop_monitoring(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_monitoring
    is_monitoring = False
    
    # Try to cancel the task if it exists
    if 'monitor_task' in context.chat_data:
        try:
            context.chat_data['monitor_task'].cancel()
            del context.chat_data['monitor_task']
            print("🛑 Monitoring task cancelled")
        except Exception as e:
            print(f"⚠️ Error cancelling task: {str(e)}")
    
    await update.message.reply_text("🛑 Monitoring stopped")

async def purge_urls(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global monitored_urls
    monitored_urls.clear()
    await update.message.reply_text("✅ All URLs purged!")

async def start_monitoring(application: Application):
    global is_monitoring
    bot = application.bot
    await send_notification(bot, "🔔 Monitoring started!")
    print("🔍 Entering monitoring loop")
    
    while is_monitoring:
        try:
            print(f"🔄 Running URL check cycle - {len(monitored_urls)} URLs")
            start_time = time.time()
            await check_urls(bot)
            elapsed = time.time() - start_time
            wait_time = max(CHECK_INTERVAL - elapsed, 5)
            print(f"✓ Check complete in {elapsed:.2f}s, waiting {wait_time:.2f}s before next check")
            await asyncio.sleep(wait_time)
        except asyncio.CancelledError:
            print("🚫 Monitoring task was cancelled")
            break
        except Exception as e:
            print(f"🚨 Monitoring error: {str(e)}")
            print(traceback.format_exc())
            # Add a shorter sleep on error to prevent rapid failure loops
            await asyncio.sleep(30)
    
    print("👋 Exiting monitoring loop")
    await send_notification(bot, "🔴 Monitoring stopped!")

def main():
    try:
        global CHROME_PATH, CHROMEDRIVER_PATH
        
        print(f"🚀 Starting bot at {datetime.now()}")
        kill_previous_instances()

        # Debug environment info
        print(f"🌍 Operating System: {platform.system()}")
        print(f"🌍 Running on Render: {IS_RENDER}")
        print(f"💾 Chrome path: {CHROME_PATH}")
        print(f"💾 Chromedriver path: {CHROMEDRIVER_PATH}")
        
        # Only check files locally, not on Render
        if not IS_RENDER:
            print(f"📂 Chrome exists: {os.path.exists(CHROME_PATH)}")
            print(f"📂 Chromedriver exists: {os.path.exists(CHROMEDRIVER_PATH)}")
            
            # Try to find Chrome and Chromedriver if not at expected locations
            chrome_path_to_use = CHROME_PATH
            chromedriver_path_to_use = CHROMEDRIVER_PATH
            
            if not os.path.exists(chrome_path_to_use):
                if platform.system() == "Windows":
                    chrome_possible_paths = [
                        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
                    ]
                    for path in chrome_possible_paths:
                        if os.path.exists(path):
                            print(f"✅ Found Chrome at: {path}")
                            chrome_path_to_use = path
                            break
            
            if not os.path.exists(chromedriver_path_to_use):
                chromedriver_in_path = shutil.which('chromedriver')
                if chromedriver_in_path:
                    print(f"✅ Found Chromedriver in PATH: {chromedriver_in_path}")
                    chromedriver_path_to_use = chromedriver_in_path
                    
            # Update global variables with found paths
            if chrome_path_to_use != CHROME_PATH or chromedriver_path_to_use != CHROMEDRIVER_PATH:
                CHROME_PATH = chrome_path_to_use
                CHROMEDRIVER_PATH = chromedriver_path_to_use
                print(f"📌 Using Chrome at: {CHROME_PATH}")
                print(f"📌 Using Chromedriver at: {CHROMEDRIVER_PATH}")
        
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

        print("Creating Telegram application...")
        application = (
            Application.builder()
            .token(TELEGRAM_BOT_TOKEN)
            .concurrent_updates(True)
            .post_init(lambda app: app.bot.delete_webhook(drop_pending_updates=True))
            .build()
        )

        print("Adding handlers...")
        application.add_handler(MessageHandler(filters.ALL, auth_middleware), group=-1)
        handlers = [
            CommandHandler("start", start),
            CommandHandler("add", add_url),
            CommandHandler("list", list_urls),
            CommandHandler("run", run_monitoring),
            CommandHandler("stop", stop_monitoring),
            CommandHandler("purge", purge_urls)
        ]
        for handler in handlers:
            application.add_handler(handler)

        print("Starting polling...")
        application.run_polling()
    except KeyboardInterrupt:
        print("\n🛑 Graceful shutdown")
    except Exception as e:
        print(f"❌ CRITICAL ERROR: {str(e)}")
        print(traceback.format_exc())
        input("Press Enter to exit...")
    finally:
        try:
            executor.shutdown()
        except:
            pass
        print("🧹 Cleaning up...")

if __name__ == "__main__":
    print("Script starting...")
    try:
        main()
    except Exception as e:
        print(f"❌ CRITICAL ERROR in __main__: {str(e)}")
        print(traceback.format_exc())
        input("Press Enter to exit...")