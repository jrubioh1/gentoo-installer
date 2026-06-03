import subprocess
import os
import sys
import time
from pydicts import colors

def run_command(cmd, input_text=None, capture=True):
    """Utility to run shell commands with optional input."""
    try:
        result = subprocess.run(
            cmd, 
            input=input_text, 
            text=True, 
            check=True, 
            capture_output=capture
        )
        return True, result.stdout
    except subprocess.CalledProcessError as e:
        return False, e.stderr

def setup_luks(root_partition):
    """Sets up LUKS encryption on the root partition."""
    print(colors.magenta(f"\n[*] Setting up LUKS encryption on {root_partition}..."))
    
    password = input(colors.white("    Enter LUKS Passphrase: ")).strip()
    if not password:
        print(colors.red("[✗] Password cannot be empty."))
        return None

    # 1. Format with LUKS
    # --batch-mode to avoid confirmation prompt, passing password via stdin
    print(colors.cyan("    [+] Formatting partition with LUKS..."))
    cmd_format = ["cryptsetup", "luksFormat", "--batch-mode", root_partition]
    success, err = run_command(cmd_format, input_text=password)
    if not success:
        print(colors.red(f"    [✗] LUKS format failed: {err}"))
        return None

    # 2. Open LUKS container
    mapper_name = "cryptroot"
    print(colors.cyan(f"    [+] Opening LUKS container as /dev/mapper/{mapper_name}..."))
    cmd_open = ["cryptsetup", "open", root_partition, mapper_name]
    success, err = run_command(cmd_open, input_text=password)
    if not success:
        print(colors.red(f"    [✗] LUKS open failed: {err}"))
        return None

    return f"/dev/mapper/{mapper_name}"

def format_devices(boot_part, root_device, boot_fs, root_fs):
    """Formats the boot and (encrypted) root devices."""
    print(colors.magenta("\n[*] Formatting devices..."))
    
    # Format Boot
    print(colors.cyan(f"    [+] Formatting boot ({boot_part}) as {boot_fs}..."))
    if boot_fs == 'vfat':
        cmd_boot = ["mkfs.vfat", "-F", "32", boot_part]
    else:
        cmd_boot = [f"mkfs.{boot_fs}", boot_part]
    
    success, err = run_command(cmd_boot)
    if not success:
        print(colors.red(f"    [✗] Boot format failed: {err}"))
        return False

    # Format Root
    print(colors.cyan(f"    [+] Formatting root ({root_device}) as {root_fs}..."))
    cmd_root = [f"mkfs.{root_fs}", root_device]
    success, err = run_command(cmd_root)
    if not success:
        print(colors.red(f"    [✗] Root format failed: {err}"))
        return False

    return True

def deploy_stage(stage_path, mount_point):
    """Extracts the Stage3 tarball to the mount point."""
    print(colors.magenta(f"\n[*] Deploying Stage3 tarball to {mount_point}..."))
    
    # Extraction command (using --xattrs-include='*.*' for Gentoo)
    cmd = ["tar", "xpvf", stage_path, "-C", mount_point, "--xattrs-include='*.*'", "--numeric-owner"]
    
    # We don't capture output here to show progress if it's verbose, 
    # but for a cleaner UI we might want to capture or use a progress bar.
    # For now, let's just run it.
    try:
        subprocess.run(cmd, check=True)
        print(colors.green("\n[✓] Stage3 extracted successfully."))
        return True
    except subprocess.CalledProcessError as e:
        print(colors.red(f"\n[✗] Failed to extract Stage3: {e}"))
        return False

def main(stage_path, partition_info):
    """Main installer flow."""
    boot_part = partition_info['boot']
    root_part = partition_info['root']
    boot_fs = partition_info.get('boot_fs', 'vfat')
    root_fs = partition_info.get('root_fs', 'ext4')

    # 1. Setup LUKS
    encrypted_root = setup_luks(root_part)
    if not encrypted_root:
        return False

    # 2. Format
    if not format_devices(boot_part, encrypted_root, boot_fs, root_fs):
        return False

    # 3. Mount and Extract
    mount_point = "/mnt/gentoo"
    os.makedirs(mount_point, exist_ok=True)
    
    print(colors.cyan(f"\n[*] Mounting {encrypted_root} to {mount_point}..."))
    success, err = run_command(["mount", encrypted_root, mount_point])
    if not success:
        print(colors.red(f"    [✗] Failed to mount root: {err}"))
        return False

    # Create boot directory and mount it
    os.makedirs(f"{mount_point}/boot", exist_ok=True)
    print(colors.cyan(f"    [+] Mounting {boot_part} to {mount_point}/boot..."))
    success, err = run_command(["mount", boot_part, f"{mount_point}/boot"])
    if not success:
        print(colors.red(f"    [✗] Failed to mount boot: {err}"))
        return False

    # 4. Deploy
    if not deploy_stage(stage_path, mount_point):
        return False

    return True
