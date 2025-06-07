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
from dataclasses import dataclass
from typing import Dict, Optional, Tuple, List
import threading
from queue import Queue, Empty

# First check if required packages are installed
try:
    import psutil
    from dotenv import load_dotenv
    import chromedriver_autoinstaller
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
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import (
        StaleElementReferenceException,
        WebDriverException,
        TimeoutException,
        NoSuchElementException
    )
    from selenium.webdriver.chrome.service import Service
except ImportError as e:
    print(f"ERROR: Missing required package: {str(e)}")
    print("Please install required packages using:")
    print("pip install python-telegram-bot selenium python-dotenv psutil chromedriver-autoinstaller")
    if not os.getenv('IS_RENDER', 'false').lower() == 'true':
        input("Press Enter to exit...")
    sys.exit(1)

# DEFINE IS_RENDER FIRST
IS_RENDER = os.getenv('IS_RENDER', 'false').lower() == 'true'

print(f"🚀 Starting Zealy Bot - {'Render' if IS_RENDER else 'Local'} Mode")
print(f"📍 Working directory: {os.getcwd()}")
print(f"🐍 Python version: {sys.version}")

# Load environment variables
if not IS_RENDER:
    print("Loading .env file...")
    load_dotenv()

print("🔍 Loading environment variables...")

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
CHAT_ID_STR = os.getenv('CHAT_ID')

print(f"✅ Environment Check:")
print(f"   IS_RENDER: {IS_RENDER}")
print(f"   BOT_TOKEN exists: {bool(TELEGRAM_BOT_TOKEN)}")
print(f"   CHAT_ID exists: {bool(CHAT_ID_STR)}")

if TELEGRAM_BOT_TOKEN:
    print(f"   Bot token length: {len(TELEGRAM_BOT_TOKEN)}")
    print(f"   Bot token preview: {TELEGRAM_BOT_TOKEN[:10]}...")

if CHAT_ID_STR:
    print(f"   Chat ID value: '{CHAT_ID_STR}'")

# Check for missing variables
missing_vars = []
if not TELEGRAM_BOT_TOKEN:
    missing_vars.append("TELEGRAM_BOT_TOKEN")
if not CHAT_ID_STR:
    missing_vars.append("CHAT_ID")

if missing_vars:
    print(f"\n❌ Missing environment variables: {', '.join(missing_vars)}")
    if IS_RENDER:
        print("\n🔧 Render Setup Instructions:")
        print("1. Go to your Render dashboard")
        print("2. Click on your service")
        print("3. Go to Environment tab")
        print("4. Add these variables:")
        for var in missing_vars:
            if var == "TELEGRAM_BOT_TOKEN":
                print(f"   {var} = your_bot_token_from_@BotFather")
            elif var == "CHAT_ID":
                print(f"   {var} = your_chat_id_number")
        print("5. Save and redeploy")
    else:
        print("\n🔧 Local Setup Instructions:")
        print("Create a .env file with:")
        for var in missing_vars:
            if var == "TELEGRAM_BOT_TOKEN":
                print(f"{var}=your_bot_token")
            elif var == "CHAT_ID":
                print(f"{var}=your_chat_id")
    
    print(f"\n💡 After adding variables, restart the bot")
    if not IS_RENDER:
        input("Press Enter to exit...")
    sys.exit(1)

# Parse CHAT_ID
try:
    CHAT_ID = int(CHAT_ID_STR)
    print(f"✅ Chat ID parsed: {CHAT_ID}")
except ValueError:
    print(f"❌ CHAT_ID must be a number, got: '{CHAT_ID_STR}'")
    if not IS_RENDER:
        input("Press Enter to exit...")
    sys.exit(1)

# Chrome setup
print("🔧 Setting up Chrome...")
try:
    if not IS_RENDER:
        chromedriver_autoinstaller.install()
        print("✅ ChromeDriver installed")
except Exception as e:
    print(f"⚠️ ChromeDriver auto-install warning: {e}")

# Configuration
CHECK_INTERVAL = 30
MAX_URLS = 10
ZEALY_CONTAINER_SELECTOR = "div.flex.flex-col.w-full.pt-100"
REQUEST_TIMEOUT = 15
MAX_RETRIES = 2
RETRY_DELAY_BASE = 3
FAILURE_THRESHOLD = 5

# Set Chrome paths
if IS_RENDER:
    CHROME_PATH = '/usr/bin/chromium'
    CHROMEDRIVER_PATH = '/usr/bin/chromedriver'
elif platform.system() == "Windows":
    CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    CHROMEDRIVER_PATH = shutil.which('chromedriver') or r"C:\chromedriver\chromedriver.exe"
else:
    CHROME_PATH = '/usr/bin/google-chrome'
    CHROMEDRIVER_PATH = shutil.which('chromedriver') or '/usr/bin/chromedriver'

def kill_previous_instances():
    """Kill any previous bot instances"""
    current_pid = os.getpid()
    try:
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                if 'python' in proc.info['name'].lower():
                    cmdline = ' '.join(proc.info['cmdline'])
                    if 'zealy' in cmdline.lower() and proc.info['pid'] != current_pid:
                        print(f"🚨 Killing previous instance (PID: {proc.info['pid']})")
                        proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                continue
    except Exception as e:
        print(f"Warning: Error checking previous instances: {e}")

def get_chrome_options():
    """Get optimized Chrome options"""
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1280,720")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-plugins")
    options.add_argument("--disable-images")
    options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    # Memory optimizations
    options.add_argument("--memory-pressure-off")
    options.add_argument("--aggressive-cache-discard")
    options.add_argument("--disable-background-timer-throttling")
    options.add_argument("--disable-backgrounding-occluded-windows")
    options.add_argument("--disable-renderer-backgrounding")
    options.add_argument("--disable-background-networking")
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--disable-accelerated-2d-canvas")
    options.add_argument("--disable-default-apps")
    options.add_argument("--disable-sync")
    options.add_argument("--disable-translate")
    options.add_argument("--disable-logging")
    options.add_argument("--log-level=3")
    
    if IS_RENDER:
        options.add_argument("--disable-setuid-sandbox")
        options.add_argument("--single-process")
        options.add_argument("--no-zygote")
        options.add_argument("--no-first-run")
        options.add_argument("--disable-infobars")
        options.add_argument("--disable-dev-tools")
        options.add_argument("--max_old_space_size=256")
        options.add_argument("--js-flags=--max-old-space-size=256")
    else:
        options.add_argument("--max_old_space_size=512")
        options.add_argument("--js-flags=--max-old-space-size=512")
    
    # Set Chrome binary path
    if os.path.exists(CHROME_PATH):
        options.binary_location = CHROME_PATH
    elif not IS_RENDER and platform.system() == "Windows":
        # Try common Windows Chrome paths
        possible_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
        ]
        for path in possible_paths:
            if os.path.exists(path):
                options.binary_location = path
                break
    
    return options

@dataclass
class URLData:
    hash: str
    last_notified: float
    last_checked: float
    failures: int
    consecutive_successes: int
    last_error: Optional[str] = None
    check_count: int = 0
    avg_response_time: float = 0.0
    
    def update_response_time(self, response_time: float):
        """Update average response time"""
        if self.avg_response_time == 0:
            self.avg_response_time = response_time
        else:
            self.avg_response_time = 0.7 * self.avg_response_time + 0.3 * response_time

# Global variables
monitored_urls: Dict[str, URLData] = {}
is_monitoring = False
notification_queue = Queue()

def create_driver():
    """Create a single Chrome driver instance"""
    try:
        options = get_chrome_options()
        
        if IS_RENDER or not os.path.exists(CHROMEDRIVER_PATH):
            driver = webdriver.Chrome(options=options)
        else:
            service = Service(executable_path=CHROMEDRIVER_PATH)
            driver = webdriver.Chrome(service=service, options=options)
        
        driver.set_page_load_timeout(REQUEST_TIMEOUT)
        driver.implicitly_wait(5)
        print("✅ Driver created successfully")
        return driver
        
    except Exception as e:
        print(f"❌ Failed to create driver: {e}")
        return None

def get_content_hash_fast(url: str, debug_mode: bool = False) -> Tuple[Optional[str], float, Optional[str], Optional[str]]:
    """Get content hash for URL with cleaning"""
    driver = None
    start_time = time.time()
    
    try:
        print(f"🌐 Loading URL: {url}")
        driver = create_driver()
        
        if not driver:
            return None, time.time() - start_time, "Failed to create driver", None
        
        driver.get(url)
        print("⏳ Waiting for React to render...")
        time.sleep(3)  # Wait for React to load
        
        print("⏳ Waiting for page elements...")
        # Try different selectors
        selectors = [
            ZEALY_CONTAINER_SELECTOR,
            "div[class*='flex'][class*='flex-col']",
            "main",
            "body"
        ]
        
        container = None
        for selector in selectors:
            try:
                container = WebDriverWait(driver, 8).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                )
                print(f"✅ Found element with selector: {selector}")
                break
            except TimeoutException:
                print(f"⚠️ Selector {selector} not found, trying next...")
                continue
        
        if not container:
            return None, time.time() - start_time, "No suitable container found", None
        
        time.sleep(1)  # Additional wait
        content = container.text
        
        if not content or len(content.strip()) < 10:
            return None, time.time() - start_time, f"Content too short: {len(content)} chars", None
        
        print(f"📄 Content retrieved, length: {len(content)} chars")
        
        # Enhanced content cleaning
        clean_content = content
        
        # Remove timestamps and dates
        clean_content = re.sub(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?Z?', '', clean_content)
        clean_content = re.sub(r'\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM)?', '', clean_content)
        clean_content = re.sub(r'(?:\d+\s*(?:seconds?|mins?|minutes?|hours?|days?|weeks?|months?|years?)\s*ago)', '', clean_content, flags=re.IGNORECASE)
        clean_content = re.sub(r'(?:just now|moments? ago|recently)', '', clean_content, flags=re.IGNORECASE)
        
        # Remove XP and point systems
        clean_content = re.sub(r'\d+\s*(?:XP|points?|pts)', '', clean_content, flags=re.IGNORECASE)
        clean_content = re.sub(r'(?:XP|points?|pts)\s*:\s*\d+', '', clean_content, flags=re.IGNORECASE)
        
        # Remove UUIDs and session identifiers
        clean_content = re.sub(r'\b[A-F0-9]{8}-(?:[A-F0-9]{4}-){3}[A-F0-9]{12}\b', '', clean_content, flags=re.IGNORECASE)
        clean_content = re.sub(r'\b[a-f0-9]{32}\b', '', clean_content, flags=re.IGNORECASE)
        clean_content = re.sub(r'\b[a-f0-9]{40}\b', '', clean_content, flags=re.IGNORECASE)
        
        # Remove view counts and engagement metrics
        clean_content = re.sub(r'\d+\s*(?:views?|likes?|shares?|comments?|replies?)', '', clean_content, flags=re.IGNORECASE)
        clean_content = re.sub(r'(?:views?|likes?|shares?|comments?|replies?)\s*:\s*\d+', '', clean_content, flags=re.IGNORECASE)
        
        # Remove online/active user counts
        clean_content = re.sub(r'\d+\s*(?:online|active|members?|users?)', '', clean_content, flags=re.IGNORECASE)
        clean_content = re.sub(r'(?:online|active|members?|users?)\s*:\s*\d+', '', clean_content, flags=re.IGNORECASE)
        
        # Remove progress indicators and percentages
        clean_content = re.sub(r'\d+%|\d+/\d+', '', clean_content)
        clean_content = re.sub(r'(?:progress|completed|remaining)\s*:\s*\d+', '', clean_content, flags=re.IGNORECASE)
        
        # Remove dynamic counters
        clean_content = re.sub(r'\d+\s*(?:total|count|number)', '', clean_content, flags=re.IGNORECASE)
        clean_content = re.sub(r'(?:total|count|number)\s*:\s*\d+', '', clean_content, flags=re.IGNORECASE)
        
        # Remove rank and position indicators
        clean_content = re.sub(r'(?:rank|position)\s*#?\d+', '', clean_content, flags=re.IGNORECASE)
        clean_content = re.sub(r'#\d+\s*(?:rank|position)', '', clean_content, flags=re.IGNORECASE)
        
        # Remove session-specific data
        clean_content = re.sub(r'session\s*[a-f0-9]+', '', clean_content, flags=re.IGNORECASE)
        clean_content = re.sub(r'token\s*[a-f0-9]+', '', clean_content, flags=re.IGNORECASE)
        
        # Remove loading states
        clean_content = re.sub(r'(?:loading|refreshing|updating)\.{0,3}', '', clean_content, flags=re.IGNORECASE)
        
        # Normalize whitespace
        clean_content = re.sub(r'\s+', ' ', clean_content)
        clean_content = clean_content.strip()
        
        # Additional Zealy-specific filtering
        clean_content = re.sub(r'(?:quest|task)\s+\d+\s*(?:of|/)\s*\d+', '', clean_content, flags=re.IGNORECASE)
        clean_content = re.sub(r'(?:day|week|month)\s+\d+', '', clean_content, flags=re.IGNORECASE)
        
        print(f"📄 Content cleaned, original: {len(content)} chars, cleaned: {len(clean_content)} chars")
        
        content_hash = hashlib.sha256(clean_content.encode()).hexdigest()
        response_time = time.time() - start_time
        
        # Return sample for debugging if requested
        content_sample = content[:500] if debug_mode else None
        
        print(f"🔢 Hash generated: {content_hash[:8]}... in {response_time:.2f}s")
        return content_hash, response_time, None, content_sample
        
    except Exception as e:
        error_msg = f"Error: {str(e)}"
        print(f"❌ {error_msg}")
        return None, time.time() - start_time, error_msg, None
        
    finally:
        if driver:
            try:
                driver.quit()
            except Exception as e:
                print(f"⚠️ Error closing driver: {e}")

async def check_single_url(url: str, url_data: URLData) -> Tuple[str, bool, Optional[str]]:
    """Check a single URL for changes"""
    retry_count = 0
    last_error = None
    
    while retry_count < MAX_RETRIES:
        try:
            loop = asyncio.get_event_loop()
            hash_result, response_time, error, content_sample = await loop.run_in_executor(
                None, get_content_hash_fast, url, False
            )
            
            if hash_result is None:
                retry_count += 1
                last_error = error or "Unknown error"
                
                if retry_count < MAX_RETRIES:
                    delay = RETRY_DELAY_BASE ** retry_count
                    print(f"⏳ Retrying {url} in {delay:.1f}s (attempt {retry_count + 1}/{MAX_RETRIES})")
                    await asyncio.sleep(delay)
                    continue
                else:
                    url_data.failures += 1
                    url_data.consecutive_successes = 0
                    url_data.last_error = last_error
                    print(f"❌ Max retries reached for {url}. Failure #{url_data.failures}")
                    return url, False, last_error
            
            # Success case
            url_data.failures = 0
            url_data.consecutive_successes += 1
            url_data.last_error = None
            url_data.check_count += 1
            url_data.update_response_time(response_time)
            url_data.last_checked = time.time()
            
            # Check for changes
            has_changes = url_data.hash != hash_result
            if has_changes:
                print(f"🔔 Change detected for {url}")
                url_data.hash = hash_result
                return url, True, None
            else:
                print(f"✓ No changes for {url} (avg: {url_data.avg_response_time:.2f}s)")
                return url, False, None
                
        except Exception as e:
            retry_count += 1
            last_error = f"Unexpected error: {str(e)}"
            print(f"⚠️ Error checking {url}: {last_error}")
            
            if retry_count < MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAY_BASE ** retry_count)
            else:
                url_data.failures += 1
                url_data.consecutive_successes = 0
                url_data.last_error = last_error
                return url, False, last_error
    
    return url, False, last_error

async def send_notification(bot, message: str, priority: bool = False):
    """Send Telegram notification"""
    retries = 0
    backoff_delay = 1
    
    while retries < 3:
        try:
            await bot.send_message(chat_id=CHAT_ID, text=message)
            print(f"✅ Sent notification: {message[:50]}...")
            return True
        except (TelegramError, NetworkError) as e:
            print(f"📡 Network error: {str(e)} - Retry {retries+1}/3")
            retries += 1
            if retries < 3:
                await asyncio.sleep(backoff_delay)
                backoff_delay *= 2
    
    print(f"❌ Failed to send notification after 3 retries")
    return False

async def check_urls_sequential(bot):
    """Check URLs sequentially (one by one)"""
    global monitored_urls
    current_time = time.time()
    
    if not monitored_urls:
        print("⚠️ No URLs to check")
        return
    
    print(f"🔍 Checking {len(monitored_urls)} URLs sequentially...")
    
    changes_detected = 0
    urls_to_remove = []
    
    for url, url_data in list(monitored_urls.items()):
        try:
            result = await check_single_url(url, url_data)
            
            if isinstance(result, Exception):
                print(f"⚠️ Task exception: {result}")
                continue
                
            url, has_changes, error = result
            
            if url not in monitored_urls:
                continue
                
            url_data = monitored_urls[url]
            
            if has_changes:
                changes_detected += 1
                # Check rate limiting for notifications
                if current_time - url_data.last_notified > 60:
                    await send_notification(
                        bot, 
                        f"🚨 CHANGE DETECTED!\n{url}\nAvg response: {url_data.avg_response_time:.2f}s\nCheck #{url_data.check_count}",
                        priority=True
                    )
                    url_data.last_notified = current_time
            
            # Handle failures
            if url_data.failures > FAILURE_THRESHOLD:
                urls_to_remove.append(url)
            elif url_data.failures > 2 and url_data.consecutive_successes == 0:
                await send_notification(
                    bot,
                    f"⚠️ Monitoring issues for {url}\nFailures: {url_data.failures}/{FAILURE_THRESHOLD}\nLast error: {url_data.last_error or 'Unknown'}"
                )
                
        except Exception as e:
            print(f"⚠️ Error processing URL {url}: {e}")
    
    # Remove problematic URLs
    for url in urls_to_remove:
        del monitored_urls[url]
        await send_notification(
            bot, 
            f"🔴 Removed from monitoring (too many failures): {url}",
            priority=True
        )
        print(f"🗑️ Removed {url} after {FAILURE_THRESHOLD} failures")
    
    print(f"✅ Sequential check complete: {changes_detected} changes, {len(urls_to_remove)} removed")

# AUTH MIDDLEWARE
async def auth_middleware(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id
    print(f"📨 Message from chat ID: {user_id}")
    print(f"📨 Expected chat ID: {CHAT_ID}")
    print(f"📨 Match: {user_id == CHAT_ID}")
    
    if user_id != CHAT_ID:
        print(f"🚫 Unauthorized access from chat ID: {user_id}")
        await update.message.reply_text(f"🚫 Unauthorized access! Your chat ID: {user_id}")
        raise ApplicationHandlerStop
    else:
        print(f"✅ Authorized access from chat ID: {user_id}")

# COMMAND HANDLERS
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("📨 /start command received!")
    await update.message.reply_text(
        "🚀 Zealy Monitoring Bot\n\n"
        "Commands:\n"
        "/add <url> - Add Zealy URL to monitor\n"
        "/remove <number> - Remove URL by number\n"
        "/list - Show monitored URLs\n"
        "/run - Start monitoring\n"
        "/stop - Stop monitoring\n"
        "/status - Show monitoring statistics\n"
        "/debug <number> - Debug URL content\n"
        "/purge - Remove all URLs\n"
        f"\nMax URLs: {MAX_URLS}\n"
        f"Check interval: {CHECK_INTERVAL}s\n"
        "Memory optimized for low-resource environments!"
    )

async def add_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("📨 /add command received!")
    
    if len(monitored_urls) >= MAX_URLS:
        await update.message.reply_text(f"❌ Maximum URLs limit ({MAX_URLS}) reached")
        return
    
    if not context.args or not context.args[0]:
        await update.message.reply_text("❌ Usage: /add <zealy-url>")
        return
    
    url = context.args[0].lower()
    print(f"📥 Attempting to add URL: {url}")
    
    if not re.match(r'^https://(www\.)?zealy\.io/cw/[\w/-]+', url):
        await update.message.reply_text("❌ Invalid Zealy URL format")
        return
    
    if url in monitored_urls:
        await update.message.reply_text("ℹ️ URL already monitored")
        return
    
    processing_msg = await update.message.reply_text("⏳ Verifying URL...")
    
    try:
        loop = asyncio.get_event_loop()
        print(f"🔄 Getting initial hash for {url}")
        initial_hash, response_time, error, content_sample = await loop.run_in_executor(
            None, get_content_hash_fast, url, False
        )
        
        if not initial_hash:
            await processing_msg.edit_text(f"❌ Failed to verify URL: {error}")
            return
        
        monitored_urls[url] = URLData(
            hash=initial_hash,
            last_notified=0,
            last_checked=time.time(),
            failures=0,
            consecutive_successes=1,
            check_count=1,
            avg_response_time=response_time
        )
        
        print(f"✅ URL added successfully: {url}")
        await processing_msg.edit_text(
            f"✅ Added: {url}\n"
            f"📊 Now monitoring: {len(monitored_urls)}/{MAX_URLS}\n"
            f"⚡ Initial response: {response_time:.2f}s"
        )
        
    except Exception as e:
        print(f"❌ Error while getting initial hash: {str(e)}")
        try:
            await processing_msg.edit_text(f"❌ Failed to add URL: {str(e)}")
        except:
            print(f"❌ Could not edit message: {str(e)}")

async def list_urls(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not monitored_urls:
        await update.message.reply_text("📋 No URLs monitored")
        return
    
    message_lines = ["📋 Monitored URLs:\n"]
    for idx, (url, data) in enumerate(monitored_urls.items(), 1):
        status = "✅" if data.failures == 0 else f"⚠️({data.failures})"
        message_lines.append(f"{idx}. {status} {url}")
    
    message_lines.append(f"\n📊 Using {len(monitored_urls)}/{MAX_URLS} slots")
    message = "\n".join(message_lines)[:4000]
    await update.message.reply_text(message)

async def remove_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not monitored_urls:
        await update.message.reply_text("❌ No URLs to remove")
        return
    
    if not context.args or not context.args[0]:
        await update.message.reply_text("❌ Usage: /remove <number>\nUse /list to see URL numbers")
        return
    
    try:
        url_index = int(context.args[0]) - 1
        url_list = list(monitored_urls.keys())
        
        if url_index < 0 or url_index >= len(url_list):
            await update.message.reply_text(f"❌ Invalid number. Use a number between 1 and {len(url_list)}")
            return
        
        url_to_remove = url_list[url_index]
        del monitored_urls[url_to_remove]
        
        await update.message.reply_text(
            f"✅ Removed: {url_to_remove}\n📊 Now monitoring: {len(monitored_urls)}/{MAX_URLS}"
        )
        print(f"🗑️ Manually removed URL: {url_to_remove}")
        
    except ValueError:
        await update.message.reply_text("❌ Please provide a valid number")
    except Exception as e:
        print(f"⚠️ Error in remove_url: {str(e)}")
        await update.message.reply_text(f"❌ Error removing URL: {str(e)}")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not monitored_urls:
        await update.message.reply_text("📊 No URLs being monitored")
        return
    
    status_lines = ["📊 Monitoring Statistics:\n"]
    
    for url, data in monitored_urls.items():
        status_lines.append(
            f"🔗 {url[:50]}...\n"
            f"   ✅ Checks: {data.check_count} | Failures: {data.failures}\n"
            f"   ⚡ Avg time: {data.avg_response_time:.2f}s\n"
            f"   🕐 Last: {time.time() - data.last_checked:.0f}s ago"
        )
        
        if data.last_error:
            status_lines.append(f"   ❌ Error: {data.last_error[:30]}...")
        
        status_lines.append("")
    
    status_lines.append(f"🔄 Monitoring: {'✅ Active' if is_monitoring else '❌ Stopped'}")
    status_lines.append(f"💾 Memory optimized for low-resource environments")
    
    message = "\n".join(status_lines)[:4000]
    await update.message.reply_text(message)

async def debug_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Debug command to see what content is being monitored for a URL"""
    if not context.args or not context.args[0]:
        await update.message.reply_text("❌ Usage: /debug <number>\nUse /list to see URL numbers")
        return
    
    try:
        url_index = int(context.args[0]) - 1
        url_list = list(monitored_urls.keys())
        
        if url_index < 0 or url_index >= len(url_list):
            await update.message.reply_text(f"❌ Invalid number. Use a number between 1 and {len(url_list)}")
            return
        
        url = url_list[url_index]
        processing_msg = await update.message.reply_text(f"🔍 Debugging content for: {url}")
        
        # Get content in debug mode
        loop = asyncio.get_event_loop()
        hash_result, response_time, error, content_sample = await loop.run_in_executor(
            None, get_content_hash_fast, url, True  # Debug mode ON
        )
        
        if hash_result:
            current_data = monitored_urls[url]
            debug_info = [
                f"🔍 Debug Info for URL #{url_index + 1}:",
                f"📄 Current hash: {current_data.hash[:12]}...",
                f"📄 New hash: {hash_result[:12]}...",
                f"🔄 Hashes match: {'✅ Yes' if current_data.hash == hash_result else '❌ No - CHANGE DETECTED!'}",
                f"⚡ Response time: {response_time:.2f}s",
                f"📊 Check count: {current_data.check_count}",
                f"❌ Failures: {current_data.failures}",
                "",
                "📝 Content sample (first 400 chars):",
                f"```{content_sample[:400] if content_sample else 'No sample available'}```"
            ]
            
            debug_message = "\n".join(debug_info)
            await processing_msg.edit_text(debug_message[:4000])
        else:
            await processing_msg.edit_text(f"❌ Failed to get content: {error}")
            
    except ValueError:
        await update.message.reply_text("❌ Please provide a valid number")
    except Exception as e:
        await update.message.reply_text(f"❌ Debug error: {str(e)}")

async def run_monitoring(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_monitoring
    
    if is_monitoring:
        await update.message.reply_text("⚠️ Already monitoring")
        return
    
    if not monitored_urls:
        await update.message.reply_text("❌ No URLs to monitor")
        return
    
    try:
        is_monitoring = True
        monitor_task = asyncio.create_task(start_monitoring(context.application.bot))
        context.chat_data['monitor_task'] = monitor_task
        
        await update.message.reply_text(
            f"✅ Monitoring started!\n"
            f"🔍 Checking {len(monitored_urls)} URLs every {CHECK_INTERVAL}s\n"
            f"💾 Sequential processing (memory optimized)"
        )
        print("✅ Monitoring tasks created and started")
        
    except Exception as e:
        is_monitoring = False
        await update.message.reply_text(f"❌ Failed to start monitoring: {str(e)}")
        print(f"❌ Error starting monitoring: {str(e)}")

async def stop_monitoring(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_monitoring
    is_monitoring = False
    
    # Cancel monitoring task
    if 'monitor_task' in context.chat_data:
        try:
            context.chat_data['monitor_task'].cancel()
            del context.chat_data['monitor_task']
            print("🛑 Monitor task cancelled")
        except Exception as e:
            print(f"⚠️ Error cancelling monitor task: {str(e)}")
    
    await update.message.reply_text("🛑 Monitoring stopped")

async def purge_urls(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global monitored_urls
    count = len(monitored_urls)
    monitored_urls.clear()
    await update.message.reply_text(f"✅ All {count} URLs purged!")

async def start_monitoring(bot):
    """Main monitoring loop"""
    global is_monitoring
    await send_notification(bot, "🔔 Monitoring started!")
    print("🔍 Entering monitoring loop")
    
    while is_monitoring:
        try:
            print(f"🔄 Running sequential URL check cycle - {len(monitored_urls)} URLs")
            start_time = time.time()
            
            await check_urls_sequential(bot)
            
            elapsed = time.time() - start_time
            wait_time = max(CHECK_INTERVAL - elapsed, 2)
            print(f"✓ Sequential check complete in {elapsed:.2f}s, waiting {wait_time:.2f}s")
            
            await asyncio.sleep(wait_time)
            
        except asyncio.CancelledError:
            print("🚫 Monitoring task was cancelled")
            break
        except Exception as e:
            print(f"🚨 Monitoring error: {str(e)}")
            print(traceback.format_exc())
            await asyncio.sleep(10)
    
    print("👋 Exiting monitoring loop")
    await send_notification(bot, "🔴 Monitoring stopped!")

def main():
    """Main function"""
    try:
        global CHROME_PATH, CHROMEDRIVER_PATH
        
        print(f"🚀 Starting bot at {datetime.now()}")
        print(f"🌍 Operating System: {platform.system()}")
        print(f"🌍 Running on Render: {IS_RENDER}")
        print(f"💾 Chrome path: {CHROME_PATH}")
        print(f"💾 Chromedriver path: {CHROMEDRIVER_PATH}")
        print(f"💾 Memory optimization enabled")
        
        # Kill previous instances
        kill_previous_instances()
        
        if not IS_RENDER:
            print(f"📂 Chrome exists: {os.path.exists(CHROME_PATH)}")
            print(f"📂 Chromedriver exists: {os.path.exists(CHROMEDRIVER_PATH)}")
            
            # Try to find Chrome if not at expected path
            if not os.path.exists(CHROME_PATH) and platform.system() == "Windows":
                chrome_possible_paths = [
                    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
                ]
                for path in chrome_possible_paths:
                    if os.path.exists(path):
                        print(f"✅ Found Chrome at: {path}")
                        CHROME_PATH = path
                        break
            
            # Try to find ChromeDriver if not at expected path
            if not os.path.exists(CHROMEDRIVER_PATH):
                chromedriver_in_path = shutil.which('chromedriver')
                if chromedriver_in_path:
                    print(f"✅ Found Chromedriver in PATH: {chromedriver_in_path}")
                    CHROMEDRIVER_PATH = chromedriver_in_path
        
        # Set event loop policy for Windows
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

        print("🔧 Creating Telegram application...")
        print(f"🤖 Bot token (first 10 chars): {TELEGRAM_BOT_TOKEN[:10]}...")
        print(f"💬 Target chat ID: {CHAT_ID}")
        
        # Create Telegram application
        application = (
            Application.builder()
            .token(TELEGRAM_BOT_TOKEN)
            .concurrent_updates(True)
            .build()
        )
        
        print("✅ Telegram application created successfully")
        
        # Add auth middleware first
        application.add_handler(MessageHandler(filters.ALL, auth_middleware), group=-1)
        
        # Add command handlers
        handlers = [
            CommandHandler("start", start),
            CommandHandler("add", add_url),
            CommandHandler("remove", remove_url),
            CommandHandler("list", list_urls),
            CommandHandler("run", run_monitoring),
            CommandHandler("stop", stop_monitoring),
            CommandHandler("purge", purge_urls),
            CommandHandler("status", status),
            CommandHandler("debug", debug_url)
        ]
        
        for handler in handlers:
            application.add_handler(handler)
        
        print("✅ All handlers added")

        print("🚀 Starting polling...")
        print(f"📡 Bot will respond to chat ID: {CHAT_ID}")
        print("✅ Bot is ready! Send /start to test.")
        
        # Start polling with proper cleanup
        application.run_polling(drop_pending_updates=True)
        
    except KeyboardInterrupt:
        print("\n🛑 Graceful shutdown requested")
    except Exception as e:
        print(f"❌ CRITICAL ERROR: {str(e)}")
        print(traceback.format_exc())
        if not IS_RENDER:
            input("Press Enter to exit...")
    finally:
        print("🧹 Cleanup complete")

if __name__ == "__main__":
    print("🚀 Starting Zealy monitoring bot...")
    try:
        main()
    except Exception as e:
        print(f"❌ CRITICAL ERROR in __main__: {str(e)}")
        print(traceback.format_exc())
        if not IS_RENDER:
            input("Press Enter to exit...")
    finally:
        print("👋 Bot shutdown complete")