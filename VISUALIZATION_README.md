# RocksDB Overhead Visualization

An interactive animation explaining how the x1.3 storage overhead is calculated for RocksDB in the deduplication use case.

## Preview

The animation includes 4 main scenes:

1. **Data Structure** - Shows the 64-byte key + 8-byte value structure
2. **Compression Test** - Demonstrates why LZ4 compression fails on high-entropy data
3. **Overhead Breakdown** - Builds up the overhead components as a stacked bar (1.0x → 1.33x)
4. **Validation** - Compares calculated value against sources

Plus 2 bonus scenes:
- **Overhead Comparison** - Compares deduplication vs other workloads
- **Key/Value Ratio Impact** - Explains why index overhead is 6.4% instead of 0.2%

## Installation

### Step 1: Install Manim

```bash
# On macOS with Homebrew
brew install py3cairo ffmpeg
pip install manim

# On Ubuntu/Debian
sudo apt install libcairo2-dev libpango1.0-dev ffmpeg
pip install manim

# On Windows
# Install ffmpeg from https://ffmpeg.org/download.html
pip install manim
```

### Step 2: Verify Installation

```bash
manim --version
```

## Usage

### Render the main animation (low quality, fast preview)

```bash
manim -pql rocksdb_overhead_visualization.py RocksDBOverheadScene
```

### Render in high quality

```bash
manim -pqh rocksdb_overhead_visualization.py RocksDBOverheadScene
```

### Render in 4K quality (production)

```bash
manim -pqk rocksdb_overhead_visualization.py RocksDBOverheadScene
```

### Render bonus scenes

```bash
# Workload comparison
manim -pql rocksdb_overhead_visualization.py OverheadComparison

# Key/Value ratio explanation
manim -pql rocksdb_overhead_visualization.py KeyValueRatioImpact
```

## Command Options

- `-p` : Preview (automatically open video after rendering)
- `-ql` : Quality Low (480p, 15fps) - fastest
- `-qm` : Quality Medium (720p, 30fps)
- `-qh` : Quality High (1080p, 60fps)
- `-qk` : Quality 4K (2160p, 60fps) - slowest
- `--format=gif` : Output as GIF instead of MP4

## Output

Videos are saved to `media/videos/rocksdb_overhead_visualization/`:
- `480p15/` - Low quality
- `720p30/` - Medium quality  
- `1080p60/` - High quality
- `2160p60/` - 4K quality

## Customization

Edit `rocksdb_overhead_visualization.py` to customize:

- **Colors**: Change component colors in the `components` list
- **Timing**: Adjust `self.wait()` durations
- **Animation speed**: Modify `run_time` parameters
- **Text size**: Change `font_size` parameters

Example:
```python
# Slow down the overhead stacking animation
self.play(
    FadeIn(bar),
    Write(label_text),
    run_time=1.5  # Default is 0.8
)
```

## Scene Breakdown

### RocksDBOverheadScene (Main)

```
Timeline:
0:00 - Title
0:02 - Data Structure (64B key + 8B value)
0:05 - Compression Test (LZ4 fails on hash)
0:09 - Overhead Breakdown (stacked bar builds up)
0:18 - Validation table
0:22 - Final result with celebration
```

### OverheadComparison (Bonus)

Compares three workloads:
- Deduplication: 1.33x (high-entropy, no compression)
- Generic Web App: 1.15x (moderate compression)
- JSON Documents: 0.8x (high compression benefit)

### KeyValueRatioImpact (Bonus)

Visual explanation of why index overhead is 6.4%:
- Shows typical web app: 20B key, 2000B value → 0.2% index
- Shows deduplication: 64B key, 8B value → 6.4% index
- Formula: Index cost ÷ Small values = Higher %

## Tips

### Fast iteration during development

Use `-ql` for quick previews:
```bash
manim -pql rocksdb_overhead_visualization.py RocksDBOverheadScene
```

### Save without opening

Remove `-p` flag:
```bash
manim -ql rocksdb_overhead_visualization.py RocksDBOverheadScene
```

### Render specific time range

```bash
manim -pql rocksdb_overhead_visualization.py RocksDBOverheadScene -n 0,60
# Renders first 60 frames only
```

### Export as GIF (for README)

```bash
manim -ql --format=gif rocksdb_overhead_visualization.py RocksDBOverheadScene
```

## Troubleshooting

### "LaTeX error" on macOS

Install LaTeX:
```bash
brew install --cask mactex-no-gui
```

### "Cairo not found"

```bash
pip install pycairo
```

### Animation too fast/slow

Adjust wait times in the code:
```python
self.wait(2)  # Increase from 1 to 2 seconds
```

## Learning Resources

- [Manim Community Docs](https://docs.manim.community/)
- [Example Gallery](https://docs.manim.community/en/stable/examples.html)
- [3Blue1Brown's Manim](https://github.com/3b1b/manim) (original)

## License

MIT License - Feel free to modify and share!
