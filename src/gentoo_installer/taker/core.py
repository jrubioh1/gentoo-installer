import re
import requests
from bs4 import BeautifulSoup
from pydicts import lod, colors
from tqdm import tqdm
from tempfile import TemporaryDirectory
import os
import subprocess
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed

# Base URL for Gentoo amd64 autobuild stages
STAGES_URL = 'https://distfiles-cdn-origin.gentoo.org/releases/amd64/autobuilds/'

# PGP Fingerprints for trusted Gentoo release keys
GENTOO_TRUSTED_FINGERPRINTS = [
    '13EBBDBEDE7A12775DFDB1BABB572E0E2D182910',  # Automated Weekly Release Key
    'D99EAC7379A850BCE47DA5F29E6438C817072058'   # Gentoo Linux Release Engineering (Main Key)
]

def print_banner():
    """Prints a professional banner for the Taker module."""
    print("\n" + colors.magenta("=" * 60))
    print(colors.magenta("      GENTOO INSTALLER - STAGE3 DISCOVERY & DOWNLOAD"))
    print(colors.magenta("=" * 60))

def check_gpg_available():
    """Checks if the 'gpg' command is available in the system PATH."""
    return shutil.which('gpg') is not None

def get_tar_files_sign_dict(url_txt, base_url):
    """
    Parses a text file (like CONTENTS or a listing) to find the .tar.xz filename
    and attempts to download its corresponding .asc PGP signature.
    """
    try:
        response = requests.get(url_txt, timeout=10)
        response.raise_for_status()
        
        tar_match = re.search(r'^([^\s]+\.tar\.xz)', response.text, re.MULTILINE)
        file = tar_match.group(1) if tar_match else None
        
        if not file:
            return {'file': None, 'sign': None}
            
        sign_url = f'{base_url}{file}.asc'
        sign_response = requests.get(sign_url, timeout=10)
        
        if sign_response.status_code != 200:
            return {'file': f'{base_url}{file}', 'sign': None}
            
        sign_content = sign_response.content
        
        if b'-----BEGIN PGP' in sign_content:
            match = re.search(b'(-----BEGIN PGP SIGNATURE-----.*?-----END PGP SIGNATURE-----)', sign_content, re.DOTALL)
            if match:
                sign_content = match.group(1)
            else:
                sign_content = sign_content.strip()

        return {'file': f'{base_url}{file}', 'sign': sign_content}
    except Exception as e:
        return {'file': None, 'sign': None}


def get_data_stage_folders(url):
    """Enters a specific stage directory to locate the tarball."""
    try:
        response = requests.get(f'{STAGES_URL}{url}', timeout=10)
        html_txt = response.text
        soup = BeautifulSoup(html_txt, 'html.parser')
        
        links = soup.find_all('a', href=True)
        links = [link['href'] for link in links if link['href'].endswith('.txt')]
        
        if not links:
            return {'file': None, 'sign': None}

        url_text_file = f'{STAGES_URL}{url}{links[0]}'
        base_url = f'{STAGES_URL}{url}'
        return get_tar_files_sign_dict(url_text_file, base_url)
    except Exception:
        return {'file': None, 'sign': None}

def parse_url(url):
    """Orchestrates metadata extraction based on link type."""
    if url.endswith('.txt'):
        url_text_file = f'{STAGES_URL}{url}'
        base_url = f'{STAGES_URL}'
        return get_tar_files_sign_dict(url_text_file, base_url)
    elif url.endswith('/'):
        return get_data_stage_folders(url)
    

def get_data_stages():
    """Scans the main Gentoo autobuild page to list all available Stage3 archives."""
    print(colors.cyan("\n[*] Scanning Gentoo mirrors for available stages..."))
    try:
        response = requests.get(STAGES_URL, timeout=10)
        html_txt = response.text
        soup = BeautifulSoup(html_txt, 'html.parser')
        
        links = [link['href'] for link in soup.find_all('a', href=True) if 'stage' in link['href'] and 'wsl' not in link['href']]
        
        results = [None] * len(links)
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_index = {executor.submit(parse_url, link): i for i, link in enumerate(links)}
            for future in tqdm(as_completed(future_to_index), total=len(links), desc=colors.cyan("    Discovering"), colour='cyan', leave=False):
                index = future_to_index[future]
                try:
                    results[index] = future.result()
                except Exception:
                    pass
        
        return [r for r in results if r is not None and r['file'] is not None]
    except Exception as e:
        print(colors.red(f"\n[✗] Error connecting to Gentoo mirrors: {e}"))
        return []

def download_file_and_verify_sign(url, output_path, sign, tmp_dir):
    """Downloads the archive and verifies its integrity."""
    print(f"\n{colors.magenta('Phase 1:')} {colors.white('Downloading Stage Archive')}")
    print(colors.white(f"    Source: {url}"))
    
    try:
        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()
        
        total_size = int(response.headers.get('content-length', 0))
        block_size = 8192
        
        with open(output_path, 'wb') as f, tqdm(
            desc=colors.green("    Progress"),
            total=total_size,
            unit='iB',
            unit_scale=True,
            unit_divisor=1024,
            colour='green',
            leave=True
        ) as bar:
            for chunk in response.iter_content(chunk_size=block_size):
                if chunk:
                    f.write(chunk)
                    bar.update(len(chunk))
        
        print(colors.green("    [✓] Download complete."))
    except Exception as e:
        print(colors.red(f"\n    [✗] Critical error during download: {e}"))
        return False

    print(f"\n{colors.magenta('Phase 2:')} {colors.white('Integrity Verification')}")
    
    if not sign:
        print(colors.yellow("    [!] Warning: No PGP signature found for this stage."))
        choice = input(colors.yellow("    [?] Continue without verification? (y/n): ")).strip().lower()
        return choice == 'y'

    if not check_gpg_available():
        print(colors.yellow("    [!] Warning: 'gpg' command not found in system."))
        choice = input(colors.yellow("    [?] Skip verification and continue? (y/n): ")).strip().lower()
        return choice == 'y'

    print(colors.white("    [*] Fetching Gentoo release keys..."))
    gpg_home = os.path.join(tmp_dir, "gpg_home")
    os.makedirs(gpg_home, mode=0o700, exist_ok=True)
    gpg_base_cmd = ["gpg", "--homedir", gpg_home, "--no-greeting", "--quiet", "--no-permission-warning"]

    keys_imported = 0
    for fingerprint in GENTOO_TRUSTED_FINGERPRINTS:
        cmd = gpg_base_cmd + ["--keyserver", "keyserver.ubuntu.com", "--recv-keys", fingerprint]
        if subprocess.run(cmd, capture_output=True).returncode == 0:
            keys_imported += 1
        else:
            cmd = gpg_base_cmd + ["--keyserver", "hkps://keys.gentoo.org", "--recv-keys", fingerprint]
            if subprocess.run(cmd, capture_output=True).returncode == 0:
                keys_imported += 1

    if keys_imported == 0:
        print(colors.yellow("    [!] Warning: Could not retrieve trusted public keys."))
        choice = input(colors.yellow("    [?] Bypass verification and continue? (y/n): ")).strip().lower()
        return choice == 'y'

    print(colors.white("    [*] Validating PGP signature..."))
    ruta_firma_temporal = os.path.join(gpg_home, "signature.asc")
    with open(ruta_firma_temporal, "wb") as f_sign:
        f_sign.write(sign.strip() + b'\n')

    cmd = gpg_base_cmd + ["--verify", ruta_firma_temporal, output_path]
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode == 0:
        print(colors.green("    [✓] INTEGRITY VERIFIED: PGP signature is valid."))
        return True
    else:
        print(colors.red("    [✗] SECURITY ALERT: Signature is INVALID or file is corrupted."))
        if result.stderr:
            print(colors.red(f"    GPG Output: {result.stderr.strip().splitlines()[-1]}"))
        
        choice = input(colors.yellow("    [?] Keep unsafe archive anyway? (y/n): ")).strip().lower()
        return choice == 'y'

def main(tmp_dir):
    """Main entry point for the stage discovery and download."""
    print_banner()
    
    stages = get_data_stages()
    if not stages:
        print(colors.red("\n[✗] No stages found. Please check your internet connection."))
        return None

    print(colors.white("\nAvailable Stage3 Builds:"))
    print(colors.white("-" * 60))
    
    # Calculate padding for nice tabular view
    max_idx_len = len(str(len(stages)))
    
    for i, stage in enumerate(stages, 1):
        filename = os.path.basename(stage['file'])
        idx_str = str(i).rjust(max_idx_len)
        has_sign = colors.green("[✓ Sign]") if stage['sign'] else colors.yellow("[No Sign]")
        print(f" {colors.cyan(idx_str)}. {colors.white(filename.ljust(45))} {has_sign}")

    print(colors.white("-" * 60))
    
    try:
        prompt = f"\n{colors.white('Select a stage (1-' + str(len(stages)) + '): ')}"
        choice = int(input(prompt))
        selected_stage = stages[choice - 1]
    except (ValueError, IndexError):
        print(colors.red("\n[✗] Invalid selection. Aborting."))
        return None

    output_path = os.path.join(tmp_dir, os.path.basename(selected_stage['file']))
    
    if download_file_and_verify_sign(selected_stage['file'], output_path, selected_stage['sign'], tmp_dir):
        print("\n" + colors.green("=" * 60))
        print(colors.green("  SUMMARY"))
        print(colors.green("-" * 60))
        print(f"  {colors.white('Status:')}    {colors.green('Success')}")
        print(f"  {colors.white('File:')}      {colors.white(os.path.basename(output_path))}")
        print(f"  {colors.white('Location:')}  {colors.white(output_path)}")
        print(colors.green("=" * 60) + "\n")
        return output_path
    else:
        print(colors.red("\n[✗] Installation process aborted."))
        return None
