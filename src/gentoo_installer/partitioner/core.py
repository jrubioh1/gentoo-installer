import subprocess
import json
import os
import shutil
import time
from pydicts import colors

def print_banner():
    """Prints a professional banner for the Partitioner module."""
    print("\n" + colors.cyan("=" * 60))
    print(colors.cyan("      GENTOO INSTALLER - CUSTOMIZABLE DISK PARTITIONING"))
    print(colors.cyan("=" * 60))

def get_available_disks():
    """Uses 'lsblk' to fetch a list of available physical disks."""
    try:
        cmd = ["lsblk", "--json", "--output", "NAME,SIZE,MODEL,TYPE,TRAN"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            return []
        data = json.loads(result.stdout)
        return [device for device in data.get('blockdevices', []) if device.get('type') == 'disk']
    except Exception as e:
        print(colors.red(f"\n[✗] Error scanning disks: {e}"))
        return []

def format_partition(partition_path, fs_type):
    """Formats a partition with the specified filesystem."""
    print(colors.cyan(f"[*] Formatting {partition_path} as {fs_type}..."))
    try:
        if fs_type == 'vfat':
            # FAT32 for EFI/Boot
            cmd = ["mkfs.vfat", "-F", "32", partition_path]
        else:
            # ext4, xfs, etc.
            cmd = [f"mkfs.{fs_type}", partition_path]
        
        # Run with check=True to catch errors
        subprocess.run(cmd, check=True, capture_output=True)
        print(colors.green(f"    [✓] Successfully formatted {partition_path}"))
        return True
    except subprocess.CalledProcessError as e:
        print(colors.red(f"    [✗] Failed to format {partition_path}: {e.stderr.decode() if e.stderr else 'Unknown error'}"))
        return False

def wipe_and_partition(device_path, boot_size):
    """
    Automates GPT partitioning using sfdisk with custom boot size.
    """
    print(colors.magenta(f"\n[*] Partitioning {device_path}..."))
    
    # sfdisk script: 
    # size=X, type=C12A7328-F81F-11D2-BA4B-00A0C93EC93B (EFI System)
    # size=+, type=0FC63DAF-8483-4772-8E79-3D69D8477DE4 (Linux Filesystem)
    sfdisk_script = (
        "label: gpt\n"
        f"size={boot_size}, type=C12A7328-F81F-11D2-BA4B-00A0C93EC93B, name='boot'\n"
        "type=0FC63DAF-8483-4772-8E79-3D69D8477DE4, name='root'\n"
    )
    
    try:
        # Wipe existing signatures first
        subprocess.run(["wipefs", "-a", device_path], check=True, capture_output=True)
        
        # Run sfdisk with the script
        subprocess.run(["sfdisk", device_path], input=sfdisk_script, text=True, check=True, capture_output=True)
        
        # Wait a bit for the kernel to reload the partition table
        time.sleep(2)
        subprocess.run(["partprobe", device_path], capture_output=True)
        
        print(colors.green(f"    [✓] GPT Partition table created successfully."))
        return True
    except subprocess.CalledProcessError as e:
        print(colors.red(f"    [✗] Partitioning failed: {e.stderr.decode() if e.stderr else 'Unknown error'}"))
        return False

def get_partition_paths(device_path):
    """Returns the paths for the newly created boot and root partitions using lsblk."""
    try:
        # Get children partitions of the device
        cmd = ["lsblk", device_path, "--json", "--output", "PATH,TYPE"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        
        # The first device is the disk itself, children are partitions
        partitions = []
        for dev in data.get('blockdevices', []):
            for child in dev.get('children', []):
                if child.get('type') == 'part':
                    partitions.append(child.get('path'))
        
        if len(partitions) >= 2:
            return partitions[0], partitions[1]
    except Exception as e:
        print(colors.yellow(f"    [!] Warning: Could not detect partitions with lsblk: {e}"))
    
    # Fallback to legacy detection if lsblk fails
    if "nvme" in device_path or "mmcblk" in device_path:
        return f"{device_path}p1", f"{device_path}p2"
    return f"{device_path}1", f"{device_path}2"

def main():
    """Customizable automated partitioning workflow."""
    print_banner()
    
    # 1. Select Disk
    disks = get_available_disks()
    if not disks:
        print(colors.red("\n[✗] No disks found."))
        return None

    print(colors.white("\nSelect target disk for Gentoo Installation:"))
    for i, disk in enumerate(disks, 1):
        name = disk.get('name', 'Unknown')
        size = disk.get('size', 'Unknown')
        model = disk.get('model') or 'Unknown Device'
        print(f" {colors.cyan(str(i))}. {colors.white(name.ljust(8))} {colors.green(size.ljust(10))} {colors.white(model)}")

    try:
        choice = int(input(f"\n{colors.white('Selection (1-' + str(len(disks)) + '): ')}"))
        selected_disk = disks[choice - 1]
    except (ValueError, IndexError):
        print(colors.red("\n[✗] Invalid selection."))
        return None

    device_path = f"/dev/{selected_disk['name']}"

    # 2. Customize Configuration
    print(colors.cyan("\n[*] Configure partition layout (Press ENTER for defaults):"))
    
    boot_size = input(f"    {colors.white('Boot size (e.g., 4G, 512M) [4G]: ')}").strip() or "4G"
    # Ensure proper GiB format for sfdisk if only number is given, but GiB/MiB is safer
    if boot_size.isdigit():
        boot_size = f"{boot_size}G"

    boot_fs = input(f"    {colors.white('Boot filesystem (vfat, ext2) [vfat]: ')}").strip() or "vfat"
    root_fs = input(f"    {colors.white('Root filesystem (ext4, xfs, btrfs) [ext4]: ')}").strip() or "ext4"

    # 3. Confirm Destructive Action
    print("\n" + colors.magenta("-" * 60))
    print(colors.magenta("  PLANNED LAYOUT"))
    print(colors.magenta("-" * 60))
    print(f"  {colors.white('Target Disk:')}    {colors.yellow(device_path)}")
    print(f"  {colors.white('Boot Part:')}     {colors.yellow(boot_size + ' (' + boot_fs + ')')}")
    print(f"  {colors.white('Root Part:')}     {colors.yellow('Remaining (' + root_fs + ')')}")
    print(colors.magenta("-" * 60))
    
    print(colors.red(f"\n[!] WARNING: ALL DATA ON {device_path} WILL BE PERMANENTLY ERASED!"))
    confirm = input(colors.red(f"Type 'YES' to confirm: ")).strip()
    
    if confirm.upper() != "YES":
        print(colors.yellow("\n[*] Aborted by user."))
        return None

    # 4. Partitioning
    if not wipe_and_partition(device_path, boot_size):
        return None

    # 5. Formatting
    p1, p2 = get_partition_paths(device_path)
    
    if format_partition(p1, boot_fs) and format_partition(p2, root_fs):
        print("\n" + colors.green("=" * 60))
        print(colors.green("  PARTITIONING SUMMARY"))
        print(colors.green("-" * 60))
        print(f"  {colors.white('Boot Device:')}  {colors.cyan(p1)} ({boot_fs})")
        print(f"  {colors.white('Root Device:')}  {colors.cyan(p2)} ({root_fs})")
        print(colors.green("=" * 60) + "\n")
        return {"boot": p1, "root": p2, "boot_fs": boot_fs, "root_fs": root_fs}
    
    return None

if __name__ == "__main__":
    main()
