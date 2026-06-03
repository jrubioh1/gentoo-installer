import argparse
from tempfile import TemporaryDirectory
import os
import sys
import shutil
from gentoo_installer.taker.core import main as taker_main
from gentoo_installer.partitioner.core import main as partitioner_main
from gentoo_installer.installer.core import main as installer_main
from pydicts import colors

def main():
    # Auto-elevate to root if necessary
    if os.geteuid() != 0:
        print(colors.yellow("\n[*] This script requires root privileges. Requesting sudo..."))
        try:
            # Re-run the current script with sudo, preserving environment (-E)
            os.execvp("sudo", ["sudo", "-E", sys.executable] + sys.argv)
        except Exception as e:
            print(colors.red(f"\n[!] Failed to elevate privileges: {e}"))
            sys.exit(1)

    parser = argparse.ArgumentParser(description="Gentoo Installer")
    parser.add_argument("--only-stage", action="store_true", help="Only run the Stage3 acquisition phase")
    parser.add_argument("--only-partition", action="store_true", help="Only run the Disk Partitioning phase")
    args = parser.parse_args()
    
    # Determine which phases to run
    run_all = not (args.only_stage or args.only_partition)
    
    print(colors.magenta("=" * 60))
    print(colors.magenta("      GENTOO LINUX INSTALLER - STARTING FLOW"))
    print(colors.magenta("=" * 60))

    partition_info = None
    stage_path = None
    tmp_dir_obj = None

    try:
        # Step 1: Stage3 Discovery and Download
        if run_all or args.only_stage:
            tmp_dir_obj = TemporaryDirectory()
            tmp_dir = tmp_dir_obj.name
            stage_path = taker_main(tmp_dir)
            if not stage_path:
                print(colors.red("\n[✗] Stage acquisition failed. Exiting."))
                sys.exit(1)
            print(colors.green(f"\n[✓] Stage3 ready for deployment."))
            if args.only_stage:
                print(colors.cyan("\n[*] Execution finished (--only-stage)."))
                return

        # Step 2: Disk Partitioning
        if run_all or args.only_partition:
            partition_info = partitioner_main()
            if not partition_info:
                print(colors.red("\n[✗] Partitioning failed or aborted. Exiting."))
                sys.exit(1)
            print(colors.green("\n[✓] Partitioning completed successfully."))
            if args.only_partition:
                print(colors.cyan("\n[*] Execution finished (--only-partition)."))
                return

        # Step 3: Deployment (LUKS, Format, Extract)
        if run_all:
            print(colors.magenta("\n" + "=" * 60))
            print(colors.magenta("      PHASE 2: ENCRYPTION, FORMATTING & DEPLOYMENT"))
            print(colors.magenta("=" * 60))
            
            if not installer_main(stage_path, partition_info):
                print(colors.red("\n[✗] Deployment failed. Exiting."))
                sys.exit(1)
                
            print(colors.green("\n[✓] Phase 1 & 2 completed successfully."))
            
    finally:
        if tmp_dir_obj:
            tmp_dir_obj.cleanup()
        
    print(colors.magenta("\n" + "=" * 60))
    print(colors.magenta("      INSTALLATION COMPLETED UP TO STAGE 3"))
    print(colors.magenta("=" * 60))


if __name__ == "__main__":
    main()
