import argparse
from tempfile import TemporaryDirectory
import os
from gentoo_installer.taker.core import main as taker_main

def main():
    parser = argparse.ArgumentParser(description="Gentoo Installer")
    #args
    args = parser.parse_args()
    
    with TemporaryDirectory() as tmp_dir:
        output_path = taker_main(tmp_dir)
        if output_path:
                print(f"Stage file is located at: {output_path}")
                
        else:
                print("Failed to obtain stage file.")
                return 1

if __name__ == "__main__":
    main()
