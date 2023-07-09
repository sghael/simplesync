#!/usr/bin/env python3
import os
import sys
import signal
import subprocess
import argparse
import configparser
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

cfg = configparser.ConfigParser()
cfg.read('simplesync.example.cfg')

ignored_dirs_from_cfg = [i.strip() for i in cfg.get('settings', 'ignored_dirs').split(',')]
ignored_files_from_cfg = [i.strip() for i in cfg.get('settings', 'ignored_files').split(',')]


def get_parser_args():
    """Parses the command-line arguments."""
    parser = argparse.ArgumentParser(description="Sync to and from remote server")
    parser.add_argument(
        "-u",
        "--remoteuser",
        type=str,
        default=os.getlogin(),
        help="Remote user. Defaults to current local use if not included.",
    )
    parser.add_argument(
        "-s", "--remoteserver", type=str, required=True, help="Remote server IP"
    )
    parser.add_argument(
        "-p", "--remoteport", type=int, default=22, help="Remote port number"
    )
    parser.add_argument(
        "-r", "--remotepath", type=str, required=True, help="Path on remote server"
    )
    parser.add_argument(
        "-l",
        "--localpath",
        type=str,
        default=os.getcwd(),
        help="Local path. Defaults to current directory if not included.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose mode")
    return parser.parse_args()


class SyncOnChanges(FileSystemEventHandler):
    """Handles events where a file system change occurs."""

    def __init__(
        self, args, ignored_dirs=ignored_dirs_from_cfg, ignored_files=ignored_files_from_cfg
    ):
        """Initializes the SSH connection and prepares for file sync."""

        self.args = args
        self.ignored_dirs = [f"--exclude={ignore}" for ignore in ignored_dirs]
        self.ignored_files = [f"--exclude='{ignore}'" for ignore in ignored_files]

        self.rsync_ssh_config = f"'ssh -p {self.args.remoteport} -o LogLevel=error -oControlPath=~/.ssh/%r@%h:%p_%l'"

        # Initialize SSH connection
        self.setup_ssh()

    def setup_ssh(self):
        """Establish an SSH connection."""

        ssh_process_list = [
            "ssh",
            "-T",
            "-l",
            self.args.remoteuser,
            "-p",
            str(self.args.remoteport),
            "-o",
            "LogLevel=error",
            "-oControlMaster=auto",
            "-oControlPath=~/.ssh/%r@%h:%p_%l",
            self.args.remoteserver,
        ]

        try:
            self.ssh_process = subprocess.Popen(
                ssh_process_list, stdout=subprocess.DEVNULL, preexec_fn=os.setsid
            )
            self.ssh_process.daemon = True
        except Exception as e:
            print("Failed to establish SSH connection")
            print(str(e))
            sys.exit(1)

    def check_ssh(self):
        """Check if the SSH process is still alive, if not restart it."""

        if self.ssh_process.poll() is not None:
            print("SSH process died. Restarting...")
            # If not, setup a new ssh connection
            self.setup_ssh()

    def rsync_exec(self):
        """Run the rsync command to sync files."""

        self.check_ssh()

        excludes = self.ignored_dirs + self.ignored_files

        remote = (
            f"{self.args.remoteuser}@{self.args.remoteserver}:{self.args.remotepath}"
        )

        command_list = [
            "rsync",
            "-azrP",
            "--no-motd",
            "-i",
            "--out-format='%i %n%L'",
            "--delete",
            "-e",
            self.rsync_ssh_config,
            *excludes,
            self.args.localpath,
            remote,
        ]

        if self.args.verbose:
            command_list.insert(3, "--verbose")
            print(" ".join(command_list))

        os.system(" ".join(command_list))

    def on_start(self):
        """Sync files on start."""

        if self.args.verbose:
            print("Sync on start.")
        self.rsync_exec()

    def on_any_event(self, event):
        """Sync files whenever any change is made."""

        if self.args.verbose:
            print(f"{event.src_path} has been {event.event_type}.")
        self.rsync_exec()


if __name__ == "__main__":
    args = get_parser_args()
    observer = Observer()
    file_system_event_handler = SyncOnChanges(args)

    def stop_sync(_, __):
        """Terminate the sync process when user stops the script."""

        print("Sync stopped by user.")
        observer.stop()
        file_system_event_handler.ssh_process.terminate()
        sys.exit(0)

    # Handle SIGINT signal
    signal.signal(signal.SIGINT, stop_sync)

    # Handle SIGTERM signal
    signal.signal(signal.SIGTERM, stop_sync)

    file_system_event_handler.on_start()

    # Start the observer, watching the current directory recursively
    observer.schedule(file_system_event_handler, path=args.localpath, recursive=True)
    observer.start()
    observer.join()
