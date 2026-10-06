# Snooker Scoreboard

A Flutter app for tracking snooker scores, managing players, and viewing leaderboards. The app is optimized for a landscape tablet layout and includes local player storage, leaderboard rankings, and sound effects.

## AI scoring foundation

The optional integration lives in `lib/ai_scoring/`, with an independent Python package in [companion/](companion/README.md). Default mode is `off`; `dry-run` records comparisons without AI controls, and `assist` exposes an optional editable suggestion in additive score entry.

**Local vision integration is experimental.** An opt-in Ollama adapter now supports recorded replay and live observation; see [Local vision scoring](docs/local-vision-scoring.md). Default-off mode, strict calibration/time/coverage gates and model latency can leave predictions unavailable. Session recording and dataset tools are available in [Record your next game](docs/record-your-next-game.md). Real-camera accuracy and production readiness are unverified.

See the [approved PRD](docs/ai-break-scoring-prd.md), [design](docs/ai-break-scoring-design.md), [implementation plan](docs/ai-break-scoring-plan.md), and [validation status](docs/ai-break-scoring-validation.md).

For integration testing, use a private, untracked Dart configuration file with these keys:

```json
{
  "AI_SCORING_MODE": "dry-run",
  "AI_SCORING_ENDPOINT": "https://companion-host:8443",
  "AI_SCORING_CAMERA_ALIAS": "table",
  "AI_SCORING_TOKEN": "<PAIRING_TOKEN>"
}
```

Run `flutter run --dart-define-from-file=/absolute/path/to/private-config.json`. Use a companion certificate trusted by the device, and matching pairing credentials in the service's protected environment. Camera credentials stay service-side and do not belong in this app configuration. For optional suggestions, choose `assist` on both app and companion; the app still needs an available visual prediction. See the companion README for startup, JSON storage and review commands.

## Requirements

Before setting up the project, install:

- Flutter SDK (stable channel)
- Android Studio with Android SDK and an emulator, or Xcode for iOS development
- Git
- A terminal with access to your shell profile

## Install Flutter SDK

If Flutter is not already installed on your machine, install it with:

```bash
git clone https://github.com/flutter/flutter.git -b stable "$HOME/flutter"
export PATH="$HOME/flutter/bin:$PATH"
flutter --version
```

To make Flutter available in every new terminal session, add this to your shell profile:

```bash
echo 'export PATH="$HOME/flutter/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

If you use bash instead of zsh, replace `~/.zshrc` with `~/.bashrc`.

## Project setup

From the project root:

```bash
cd /path/to/snooker-scoreboard
flutter doctor
flutter pub get
```

If Android tooling is missing, complete the Android setup:

```bash
flutter doctor --android-licenses
```

Then open Android Studio and install the Android SDK / create an emulator if needed.

## Run the app

Using Android emulator:

1. Open Android Studio → More Actions → Virtual Device Manager
2. Create a device (example: Pixel 6) and install a system image
3. Start the emulator
4. In the terminal, run:

```bash
cd /path/to/snooker-scoreboard
flutter devices
flutter run
```

For a specific device:

```bash
flutter run -d <device-id>
```

For a specific device:

```bash
flutter run -d <device-id>
```

On macOS, you can also launch the iOS simulator before running:

```bash
open -a Simulator
flutter run -d iPhone
```

## Run tests

```bash
cd /path/to/snooker-scoreboard
flutter test
```

## Useful project notes

- The app uses landscape mode in `lib/main.dart`
- Audio assets are configured in `pubspec.yaml`
- Player data is stored locally with shared preferences
- The project is set up for Flutter stable channel, and the current verified environment used for this repo is Flutter 3.47.0

## Troubleshooting

If `flutter` is not recognized in your terminal:

```bash
export PATH="$HOME/flutter/bin:$PATH"
source ~/.zshrc
```

If you still see issues, run:

```bash
flutter doctor -v
```

This will show any missing Android, Xcode, or Flutter SDK component that still needs to be installed.
