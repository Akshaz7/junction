# Hologram on Ash's iPhone

## Morning install

1. Unlock the iPhone and connect it to the Mac with a data-capable USB cable. Accept **Trust This Computer** on the phone and enter its passcode. Open **Xcode → Window → Devices and Simulators** if pairing needs to finish.
2. Enable **Settings → Privacy & Security → Developer Mode** on the phone. Restart and confirm when requested, then unlock it again. The phone needs iOS 18 or newer.
3. For the LAN demo, put the Mac and phone on the same network. The stable Vite preview must listen on **0.0.0.0:4173**, using `--host 0.0.0.0 --port 4173`; the API must listen on **0.0.0.0:8000**. Use the lead's stable preview, not an extra dev server. For a deployed demo, set `DEPLOY_WEB_URL` and, if the API has a separate host, `DEPLOY_API_URL` in the repo `.env`.
4. From the repo root, run this single install command:

   ```bash
   bash ios/scripts/install_on_device.sh
   ```

5. If iOS reports an untrusted developer, open **Settings → General → VPN & Device Management → Developer App**, select the development certificate, and tap **Trust**. Unlock the phone and rerun the command to launch. Allow local network and camera access; microphone and speech permissions are needed for voice.

The script selects a physical, paired iPhone, generates the Xcode project, builds with automatic signing and provisioning updates through `scripts/heavy.sh`, installs the app, and launches it. A paired phone reachable over Wi-Fi is eligible too; a USB cable is recommended for initial pairing. Discovery reads `devicectl` JSON, accepts `available (paired)` or connected phones, and excludes simulated devices and explicitly unavailable phones. Legacy JSON may report a paired phone with a disconnected tunnel before a connection is established; this is eligible for an install attempt. Build products go to `ios/build/DerivedData`. It uses the UDID for both the Xcode destination and device commands. If several phones are eligible, rerun with `--device <UDID>` from the printed list.

Signing reads `APPLE_TEAM_ID` from the repo `.env` fresh each run, or `DEVELOPMENT_TEAM` from the ignored `ios/Config/Local.xcconfig`. An exported `APPLE_TEAM_ID` overrides both; Local.xcconfig overrides `.env`. No team identifier is stored in tracked configuration. XcodeGen, Python 3, and full Xcode must be installed; `xcode-select` must point at Xcode's developer directory.

`WEB_URL` overrides `DEPLOY_WEB_URL`; otherwise the web URL is `http://<ipconfig getifaddr en0>:4173`. `API_URL` overrides `DEPLOY_API_URL`; otherwise a local web URL uses the same host on port 8000, and a deployed web URL uses its origin. Exports override matching `.env` settings. For another network interface, provide the Mac's reachable address explicitly:

```bash
WEB_URL=http://<Mac-LAN-IP>:4173 API_URL=http://<Mac-LAN-IP>:8000 bash ios/scripts/install_on_device.sh
```

URLs are passed using `-WEB_URL` and `-API_URL` launch arguments. Rerun the installer to launch with those URLs after force quitting; opening the icon alone uses the app's existing plist defaults (`localhost:5173`). The script does not change the stable web server's configuration. Ensure that server can reach its API as well.

## Local verification (I-13)

On 14 November 2026, including the attempt 2 rerun, the signed **generic iOS build succeeded**, exit 0, using the team read from `.env`, automatic signing, bundle ID `com.teamrs3.hologram`, and an Apple Development identity with an iOS Team Provisioning Profile. Xcode printed `** BUILD SUCCEEDED **`; there was no signing/provisioning error. No bundle ID fallback was needed. The full local output is in the ignored `ios/build/I-13-signed-build.log`. No device install or launch was performed during this row.

Reproduce the signed build without needing a phone:

```bash
bash ios/scripts/install_on_device.sh --build-only
```

This runs `xcodegen generate --spec ios/project.yml`, then the equivalent of:

```bash
bash scripts/heavy.sh xcodebuild \
  -project ios/Hologram.xcodeproj -scheme Hologram -configuration Debug \
  -allowProvisioningUpdates -allowProvisioningDeviceRegistration \
  -destination 'generic/platform=iOS' -derivedDataPath ios/build/DerivedData \
  CODE_SIGN_STYLE=Automatic DEVELOPMENT_TEAM='<team read from local settings>' \
  PRODUCT_BUNDLE_IDENTIFIER=com.teamrs3.hologram build
```

The placeholder in that expanded command is explanatory; use `--build-only` to read the actual local team automatically.

```bash
bash ios/scripts/install_on_device.sh --dry-run
python3 -m unittest discover -s ios/scripts -p 'test_install_on_device.py'
```

Dry-run prints signing, bundle, URL, and destination settings, discovers devices, and never builds, installs, or launches. With an eligible phone it prints `Connected paired iPhone` and `Destination: id=<UDID>`, then stops. With no eligible phone it prints `no device connected` and exits 0; an actual install exits 1 instead. All 8 installer checks passed locally. They cover device selection, configuration precedence, safe literal `.env` parsing, dry-run, and build/install/launch arguments without accessing hardware. `ios/scripts/fixtures/devices.json` is a generated, anonymized regression sample, not a capture from Ash's phone. It includes paired Wi-Fi, available, simulated, and unavailable devices in the legacy and current JSON layouts. The discovery regression test reads that saved JSON through a mocked `devicectl` invocation and verifies the detected phone is printed without invoking a build, install, or launch.

In the Codex sandbox, dry-run reached `no device connected (or CoreDevice unavailable)`. Device discovery failed with this exact diagnostic:

```text
ERROR: Command timeout of 15.0 seconds exceeded. Assuming command got stuck and aborting.
       Timed out waiting for CoreDeviceService to fully initialize. This is likely a bug in CoreDevice. Please file a bug report against CoreDevice | X. (com.apple.coredevice.devicectl error 1 (0x01))
```

The sandbox's `ipconfig getifaddr en0` also returned `ipconfig_server_port failed (os/kern) unknown error code (44c)`. Dry-run and generic builds can proceed without a LAN IP. Run the install from a normal Mac terminal with an unlocked, paired phone; set `WEB_URL` explicitly if the interface lookup still fails. **I-05 stays blocked-human until the phone is plugged in and installation/AR are verified.** A generic build does not verify device installation or AR.

## Known errors and fixes

| Error or symptom | Action |
| --- | --- |
| `no device connected` | Unlock the phone, reconnect the data cable, trust the Mac, finish pairing in Xcode's Devices and Simulators, and enable Developer Mode. Run `xcrun devicectl list devices` in a normal terminal. A physical phone listed as `available (paired)` is eligible even over Wi-Fi; the simulated Hologram iPhone is excluded. |
| A paired Wi-Fi phone is selected but Xcode/device commands cannot reach it | Reconnect by USB, unlock it, and finish device preparation in Xcode. Legacy JSON pairing alone cannot guarantee current Wi-Fi reachability. |
| CoreDevice initialization timeout above | Run outside the Codex sandbox. If it also fails in Terminal, reopen Xcode, reconnect the unlocked phone, and finish pairing before retrying. |
| `No LAN IP on en0` or the `ipconfig_server_port` error above | Connect the Mac to Wi-Fi or export `WEB_URL=http://<Mac-LAN-IP>:4173` (and `API_URL` if needed). The script prints unavailable URLs in dry-run rather than substituting localhost. |
| `Missing signing team` | Set `APPLE_TEAM_ID` in `.env`, or copy `ios/Config/Local.example.xcconfig` to ignored `Local.xcconfig` and fill `DEVELOPMENT_TEAM`. Never commit the local file. |
| Xcode reports no accounts, missing certificate, or no provisioning profile | Open **Xcode → Settings → Accounts**, sign in with Ash's Apple account, select the development team, and download profiles/create an Apple Development certificate if Xcode requests it. Accept pending Apple developer agreements. Rerun; provisioning updates and device registration are already enabled. |
| Bundle identifier is unavailable/taken | Choose a unique suffix: `BUNDLE_ID=com.teamrs3.hologram.<short-unique-suffix> bash ios/scripts/install_on_device.sh`. Record the chosen ID in the handoff. The script uses it for both build and launch; persist `BUNDLE_ID` in local `.env` for subsequent installs. |
| Device not registered / profile does not include the phone | Keep it unlocked and paired; rerun with the correct account/team. The script enables automatic device registration. If the team cannot register devices, use Xcode's signing UI to resolve membership/device limits. |
| Developer Mode disabled / untrusted developer / launch denied | Enable Developer Mode, restart and unlock, then trust the certificate under **General → VPN & Device Management**. Rerun to launch with the URL arguments. |
| Web view cannot connect, or scene/API requests fail | Open the printed URLs in iPhone Safari. Confirm the same network, Mac firewall/local network permission, preview `--host 0.0.0.0` on 4173, and API on 8000. Check `DEPLOY_API_URL` for a separate deployed API. |
| `xcodegen` missing / active developer directory points at Command Line Tools | Install XcodeGen and select the full Xcode installation using Xcode Settings → Locations → Command Line Tools. |
| iPhone OS unsupported by Xcode / device preparation in progress | Use an Xcode version supporting that iOS version and wait for preparation in Devices and Simulators, then rerun. |

Offline scenes remain available through “Show on table.” The bundled CubiCasa5K sample is CC BY-NC-SA, for non-commercial use only; scene credits are included with the resources. UI design follows Stoa's product, with permission from Stoa Technologies Oy.
