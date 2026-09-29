# XiaoGuo · A Fly-Inspired Learning Desktop Pet

**English** | [简体中文](README.zh-CN.md)

**An offline desktop pet for Windows and macOS with a fly-inspired sparse learning network.**

XiaoGuo (小果) lives in a floating, transparent desktop window. It chooses when to rest, explore, approach your pointer, or play. Your interactions update its action preferences, and its model, state, and recent memories persist between sessions.

The network is inspired by the fruit fly mushroom body. It is not a simulation of a biological connectome, and learning behavioral preferences is not evidence of consciousness.

## Quick start

### Download

Get a published version from [Releases](https://github.com/wanghao9103/xiaoguo-fly-brain-pet/releases/latest). No Python installation is required.

| Package | Platform | Run after extracting |
| --- | --- | --- |
| xiaoguo-windows-x64.zip | Windows x64 | 小果.exe |
| xiaoguo-macos-arm64.zip | Apple Silicon Mac (M series) | 小果.app |
| xiaoguo-macos-x64.zip | Intel Mac | 小果.app |

Each ZIP has a separate SHA256 checksum file on its release page. Keep the complete macOS .app bundle; you can move it into Applications and double-click it. The Mac app does not have an Apple Developer ID signature or notarization. If macOS blocks it, follow [Apple's instructions](https://support.apple.com/102445) for allowing a trusted app in System Settings → Privacy & Security.

Development builds are under **Artifacts** in successful [Build desktop apps runs](https://github.com/wanghao9103/xiaoguo-fly-brain-pet/actions/workflows/build.yml). GitHub normally requires sign-in for artifact downloads. Extract the artifact first, then the application ZIP inside it.

**The application interface currently uses Chinese labels.** English explanations below help identify the controls. The language links at the top switch this documentation.

### Run the packaged app

On Windows, double-click 小果.exe, or dist/小果.exe after a local build. Right-click the pet for the status panel, learning laboratory, Gomoku, or Chinese chess. Choose **保存并退出** (Save and exit) to close it.

The EXE and source version share the same Windows save directory, so existing memories need no migration. Exit the old instance before opening another one with the same save directory.

Optional Windows commands:

~~~powershell
.\小果.exe --lab
.\小果.exe --games
.\小果.exe --data-dir "D:\MyPetData"
~~~

These open the standalone laboratory, the board-game page, or a pet with a separate save directory.

On macOS, open 小果.app. Right-click, Control-click, or use the bottom **⋯** button for the menu. Transparent windows, context menus, and scrolling have platform-specific handling. CI checks their attributes and component behavior; visual appearance still needs confirmation on your desktop.

### Run from source

Install [Python](https://www.python.org/downloads/) with tkinter. Windows and macOS builds have been verified with Python 3.14.0.

~~~sh
git clone https://github.com/wanghao9103/xiaoguo-fly-brain-pet.git
cd xiaoguo-fly-brain-pet
python app.py
~~~

Runtime dependencies are the Python standard library and Tk. No additional runtime pip packages, GPU, cloud model, or API key is needed. The original local test environment was Windows 10, Python 3.14.0, Tk 8.6, and 200% scaling; CI also tests both Mac architectures.

On Windows, 创建桌面快捷方式.ps1 creates pet and laboratory shortcuts. The launchers 启动小果.cmd, 启动学习实验室.cmd, and 启动棋桌.cmd are also Windows-specific. After moving the project, update or recreate shortcuts that point to its old location.

Only the pet appears on startup, including the first launch. Open **状态与学习面板** (Status and learning panel) from the menu when needed, or use:

~~~sh
python app.py --panel
~~~

## Interaction guide

| Action or control | Effect |
| --- | --- |
| Click the pet | Pet it and positively reinforce the action selected at click time |
| Drag | Move it without giving a learning reward |
| Double-click, or **玩** (Play) | Start a 12-second pointer-chasing game; **停** (Stop) ends it |
| **摸 / 喂 / 玩 / 赞 / ⋯** | Pet / Feed / Play / Praise / Menu |
| Right-click | Feed, pet, encourage, discourage, pause, stay in place, or exit |
| **宠物大小** (Pet size) | Mini 156×156, small 208×208, or medium 280×280; small is the default |
| Hover, or **看看它这次的选择** | Inspect the last actual decision and its source |
| **鼓励当前动作** (Encourage current action) | Give +1 reward using the context in which the action was selected |
| **制止当前动作** (Discourage current action) | Give −1 reward using that decision context |
| **冻结学习** (Freeze learning) | Keep the pet active without changing network weights |
| **暂停活动** (Pause activity) | Pause simulated time, movement, and weight learning; manual interactions may still affect state values |
| **原地陪伴** (Stay in place) | Keep decisions and small animations, but stop moving the window |
| **保存并退出** (Save and exit) | Save memories and close the pet |

Closing the panel does not exit the pet. Esc also saves and exits when the pet has keyboard focus. Cross-monitor roaming is not supported. On Windows, movement is limited to the primary display's work area, excluding the taskbar.

Petting shows a smile, hearts, and a small hop. Feeding shows food and chewing. Dragging makes it flutter, followed by a small bounce on release. It looks up and pauses autonomous movement near the pointer, making the controls easier to click. Idle bubbles disappear to reduce obstruction.

During the chasing game, move the pointer away and let the pet approach it again. Each approach earns one point, up to three, within 12 seconds. A stationary pointer cannot repeatedly score. Stay-in-place mode still allows interaction by moving the pointer toward and away from the pet. Pausing or dragging cancels the game without a reward.

Body-click animation is immediate, but learning waits for the double-click interval so a double-click does not also count as petting. Toolbar controls respond immediately. Check the panel's current action before encouraging or discouraging it. Probabilities describe contextual action tendencies, not emotional intensity or classification confidence.

## Simulated moods during inactivity

“Inactivity” means no interaction with XiaoGuo, not that you stopped using your computer. Hovering makes it look at you but does not count as petting or produce a learning reward.

| Time without interaction | Appearance |
| --- | --- |
| Less than 45 seconds | Calm activity |
| About 45 seconds | Curious, looking around |
| About 2 minutes | Bored, drooping antennae, half-closed eyes, slower motion |
| About 5 minutes | Sleepy, quieter, occasional yawns |
| About 10 minutes | Forlorn expression and occasional tears |
| After petting or feeding | Brief happiness; inactivity timer resets |

Low energy can also cause sleepiness. Direct interaction, dragging, and games take visual priority. In a given phase, bubbles appear for at most about three seconds every 90 seconds. Most expression comes from the face and motion; the optional panel shows the mood.

Moods are read-only derivatives of existing state. They add no rewards or save fields and do not override autonomous actions. Pausing stops the inactivity timer; closed time is not replayed. These rules do not represent subjective feelings.

Crying is an animation, not a new learned action. Petting or feeding resets inactivity and briefly restores happiness. Low-energy protection, pausing, and active interactions take priority. Tears use the running simulation clock, so reaching the idle counter's limit does not freeze the animation.

## Inspecting autonomous decisions

Each autonomous decision records its inputs, probabilities, and sampled action. Hover or open the inspection menu to see a record such as “自己选：探索 · 32%” (Chose: Explore · 32%). Exploration is stochastic: the selected action need not have the highest probability.

Forced low-energy rest is identified as a protection rule; a game you start is a user command. Petting and feeding provide feedback without relabeling the previous autonomous choice. Inspection does not sample again, change weights, or consume random-generator state.

This exposes action selection, not language-based thought, self-awareness, or long-term planning. Forlorn expressions and tears remain presentation rules.

## What the network does

~~~text
12 state/environment values, each paired with its complement → 24 inputs
    ↓ Fixed random positive connections; 6 inputs per unit
384 expansion units
    ↓ Keep Top24 activations, then L2-normalize
Sparse features
    ↓ 4 trainable action-value readouts
Softmax mixed with 8% uniform exploration
    ↓
Rest / Explore / Approach / Play
~~~

Inputs encode energy, fullness, interaction satisfaction, exploration tendency, pointer distance and speed, screen edges, recent petting and feeding, inactivity, time of day, and the stay-in-place setting.

Connection indices, fixed positive projection strengths, and trainable readout weights are saved separately. The readouts contain 4 × 384 = 1,536 trainable parameters. There is no language model or cloud inference.

About every six seconds, the pet chooses an action. Immediate reward prediction error updates the selected readout row. This is a **contextual bandit**, without multi-step planning or future-return estimation. Its learning rate is 0.20, with mild decay and weight clipping.

Below 8% energy, a rule forces rest. The network did not learn that protection rule, although subsequent feedback can still update the value of resting.

## Rules, learning, and recorded memories

- **Rules:** simulated state dynamics, movement and drawing, low-energy protection, and intrinsic reward definitions.
- **Learning:** rewards for actions in a context change readout weights and future preferences.
- **Records:** recent events support inspection; they are not a language-memory system that reasons over every past experience.

Intrinsic rewards are designed immediate utility signals: rest is more suitable at low energy, while play can be more suitable with sufficient energy and exploration tendency. User feedback and intrinsic rewards update the same readouts. Later experience can change preferences; a click does not guarantee a permanent habit.

A chasing game temporarily controls the decision clock. Its reward uses the start context; cancellation gives no reward. Transient game and animation state is not saved as a persistent model, so reopening cannot replay old game rewards. Delayed clicks also retain their original action and features to avoid rewarding a different decision.

Green cells in the panel show actual sparse-layer activations. Weight-update and feedback counters reflect real updates, not decorative animation.

## Local saves and recovery

| Platform | Default data directory |
| --- | --- |
| Windows | %LOCALAPPDATA%\FlyBrainPet |
| macOS | ~/Library/Application Support/FlyBrainPet |

For isolated runs, FLYBRAINPET_DATA_DIR overrides the shared root for the pet, board games, and packaged-app reports. The --data-dir option overrides pet saves alone.

Files include:

- **memory.json:** network, random-generator state, simulated state, chosen action, pending feedback context, window position, and the last 60 events.
- **memory.backup.json:** the previous valid save.
- **memory.damaged-*.json:** preserved corrupted saves.
- **app.log:** error logs.
- **display.json:** size preferences, separate from learned weights.
- **instance.lock:** a runtime lock preventing concurrent writes to the same save.

The app saves after interactions, about every 30 seconds, and on exit. Writes use same-directory temporary files, flush, fsync, and atomic replacement. Loading validates types, shapes, numeric values, and format versions.

A damaged main save falls back to its backup while preserving the unreadable file. The app does not simulate hunger or replay rewards for time spent closed.

Only simple environmental information such as pointer position is used. The pet does not read screen content, keyboard input, or other documents, or call external services. Its optional laboratory serves a local browser interface over 127.0.0.1 without uploading data.

## Learning laboratory

Run python lab.py, use the Windows laboratory launcher, or choose **神经网络实验室（独立副本）** (Neural network laboratory — independent copy) from the pet menu. Packaged apps also accept --lab.

Adjust 12 contextual features, reward or discourage actions, and inspect probabilities and actual active units. You can apply 20 repeated rewards or sample 100 actions.

Five automated experiments cover context association, reward reversal, unfamiliar perturbations and local generalization, old/new habit interference, and local feature sensitivity. Each uses another cloned model, leaving both the manual model and real pet untouched. Automated experiments use built-in contexts; sliders affect manual experiments only.

Opened from the pet, the laboratory offers a network snapshot taken at opening time. Standalone sessions start with a blank experimental brain. Snapshots do not synchronize with the pet. A changed seed rebuilds connections only after **新建空白实验脑** (Create a blank experimental brain); automated-experiment seeds mainly control perturbation probes.

**保存实验报告** (Save experiment report) exports JSON into the source project's lab_reports directory, or the user-data directory's lab_reports subdirectory in packaged apps. The page displays the path. Reports distinguish the full model at experiment start from the current manual state; further training marks earlier results as historical.

Models live only for the laboratory session. A standalone service exits after 30 minutes without requests; a service opened from the pet stops when the pet exits. The laboratory does not open automatically.

See the [learning laboratory guide (Chinese)](docs/LEARNING_LAB.md).

## Gomoku and Chinese chess

Run python lab.py --games, use the Windows board-game launcher, or choose **和小果下棋：五子棋 / 象棋** from the pet menu. Packaged apps accept --games. Games opened from the pet menu can trigger visual reactions to moves and results.

The board supports Gomoku, Chinese chess (Xiangqi), either starting side, two search levels, undo, and new games. Separate fly-inspired sparse networks learn a search teacher's move evaluations and terminal feedback, then contribute to move selection. Each game saves its own weights. **看示范并学习 5 轮** (Watch and learn for five rounds) shows changes in actual evaluation error.

Board-game learning is separate from the rest/explore/approach/play network. Disabling it pauses both training and neural scoring without deleting memories. This is a casual practice opponent, without a guarantee of steadily improving strength. Xiangqi uses a casual repetition-draw rule, not full competitive perpetual-check and perpetual-chase adjudication.

See the [board-game guide (Chinese)](docs/CHESS.md).

## Verification

~~~sh
python -m unittest discover -v
python verify_learning.py
python verify_runtime.py
~~~

The 127 regression tests cover core behavior and persistence, gestures and games, moods, decision records, laboratory isolation and HTTP, board rules and tactics, move memory, packaging, and data directories. The suite grew from 49 pet tests to 69 with the laboratory, 122 with board games, and 127 with packaging checks.

- verify_learning.py uses synthetic contexts and never accesses real pet saves.
- verify_runtime.py uses temporary saves to check Tk layout, callbacks, drag behavior, and persistence, producing qa/verification.json. It requires a graphical desktop.
- Pet size uses explicit pixels instead of automatically doubling at 200% display scaling. The panel respects text scaling, and resizing preserves learned parameters.
- In fixed synthetic experiments, tired-context rest reached about 86.69%, active-context play 86.70%, and approach after reversed feedback 86.71%.
- Save/load preserved scores and probabilities exactly, along with the next 32 random action choices.

These measurements are not real-user success rates, biological fits, or evidence of consciousness.

GitHub Actions passed all 127 tests on Windows x64, macOS arm64, and macOS x64, then checked the packaged apps' Tk components, learning, HTML, HTTP, and saves. See the [successful build](https://github.com/wanghao9103/xiaoguo-fly-brain-pet/actions/runs/36548679116) and [verification details (Chinese)](VERIFICATION.md). Component checks are not a complete native visual review.

### Experiment without changing your pet

Windows PowerShell:

~~~powershell
python app.py --panel --data-dir "$env:TEMP\FlyBrainPet-Experiment"
~~~

macOS:

~~~sh
python app.py --panel --data-dir "/tmp/FlyBrainPet-Experiment"
~~~

These use a separate save directory. Do not overwrite real memories with synthetic test weights and describe them as preferences learned through actual interaction.

## Build and release

The [build workflow](.github/workflows/build.yml) runs on pushes to main, pull requests, and manual dispatch. Each platform tests, builds, and runs the standalone app's self-test before uploading packages. Application artifacts are retained for 30 days; diagnostic reports for 14 days.

Pushing a v* tag creates or updates its Release only after all three builds pass, with application ZIPs and SHA256 files. Ordinary branch builds have no Release write permission.

On the target OS, install Python 3.14.0 with Tk and run:

~~~sh
python -m pip install -r requirements-build.txt
python -m unittest discover -v
python ci/build_release.py
~~~

Output goes into release/. Windows builds a single EXE; macOS builds a complete .app bundle, archived with ditto to preserve executable permissions and symbolic links. Each OS builds its own binaries. The two Mac architectures have separate packages and do not require Rosetta.

For a Windows EXE-only build with dependencies isolated in the project's .venv:

~~~powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_exe.ps1
~~~

The xiaoguo.spec file explicitly includes both HTML pages, without personal saves or historical reports. To self-test the EXE with temporary saves:

~~~powershell
.\dist\小果.exe --self-test "D:\Temp\xiaoguo-check.json"
~~~

Exit code 0 and passed: true indicate success. This does not replace testing on other computers or reviewing native appearance.

## Source map

| File | Responsibility |
| --- | --- |
| brain.py | Fixed sparse encoding, TopK, action probabilities, reward learning, model validation |
| engine.py | Simulated state, decision clock, reward attribution, event memory |
| interaction.py | Transient effects and the 12-second chasing game |
| mood.py | Read-only derived moods, without weight updates |
| storage.py | Validated loading, atomic saves, corruption archives, instance locks |
| app.py | Windows/macOS window, drawing, dragging, interaction, panel |
| app_paths.py | Platform-specific persistent data paths |
| test_brain.py / test_engine.py | Core and persistence tests |
| verify_learning.py / verify_runtime.py | Synthetic learning and Tk component verification |
| experiments.py / test_experiments.py | Five controlled experiments and reproducibility checks |
| lab.py / lab.html / test_lab.py | Local laboratory, isolated models, reports, HTTP checks |
| gomoku.py / xiangqi.py | Legal moves, candidate features, search teachers |
| chess_memory.py / board_games.py / chess.html | Move learning, persistence, turns, browser board |
| desktop_entry.py / packaged_smoke.py | Packaged entry points and isolated self-tests |
| xiaoguo.spec / ci/build_release.py | Native packaging, verification, archives |
| 创建桌面快捷方式.ps1 | Windows shortcuts for the current interpreter and project |

## Documentation and research

The detailed guides currently use Chinese:

- [Architecture and capability boundaries](docs/ARCHITECTURE.md)
- [Learning laboratory: controls and metrics](docs/LEARNING_LAB.md)
- [Gomoku, Xiangqi, and sparse move learning](docs/CHESS.md)

Research background:

- [KCNet](https://arxiv.org/abs/2108.07554)
- [Fly-inspired similarity search](https://doi.org/10.1126/science.aam9868)

These studies inform the design. This is an independent educational implementation, not a reproduction of every result in those papers.
