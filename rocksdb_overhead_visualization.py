"""
RocksDB Overhead Visualization using Manim
===========================================

This animation visualizes how RocksDB's x1.3 overhead is calculated
for the deduplication use case.

Installation:
    pip install manim

Run:
    manim -pql rocksdb_overhead_visualization.py RocksDBOverheadScene
    
    Options:
    -pql : Preview, Quality Low (fast)
    -pqh : Preview, Quality High (slow but beautiful)
    -pqk : Preview, Quality 4K
"""

from manim import *
import numpy as np


class RocksDBOverheadScene(Scene):
    def construct(self):
        # Title
        title = Text("RocksDB Storage Overhead", font_size=48, color=BLUE)
        subtitle = Text("Deduplication Use Case", font_size=32, color=GRAY)
        subtitle.next_to(title, DOWN)
        
        self.play(Write(title), FadeIn(subtitle))
        self.wait(1)
        self.play(FadeOut(title), FadeOut(subtitle))
        
        # Part 1: Show the raw data structure
        self.show_data_structure()
        self.wait(1)
        
        # Part 2: Demonstrate compression failure
        self.demonstrate_compression_failure()
        self.wait(1)
        
        # Part 3: Build up the overhead components
        self.build_overhead_stack()
        self.wait(1)
        
        # Part 4: Final result
        self.show_final_result()
        self.wait(2)
    
    def show_data_structure(self):
        """Show the basic key-value structure"""
        section_title = Text("1. Data Structure", font_size=36, color=YELLOW)
        section_title.to_edge(UP)
        self.play(Write(section_title))
        
        # Create key box
        key_box = Rectangle(width=6, height=1.5, color=RED)
        key_label = Text("Key: 64 bytes", font_size=24)
        key_detail = Text("(SHA-256 hash)", font_size=18, color=GRAY)
        key_label.move_to(key_box.get_center())
        key_detail.next_to(key_label, DOWN, buff=0.1)
        key_group = VGroup(key_box, key_label, key_detail)
        key_group.shift(UP * 1.5)
        
        # Create value box
        value_box = Rectangle(width=0.75, height=1.5, color=GREEN)
        value_label = Text("Val", font_size=20, color=WHITE)
        value_detail = Text("8B", font_size=16, color=GRAY)
        value_label.move_to(value_box.get_center())
        value_detail.next_to(value_label, DOWN, buff=0.05)
        value_group = VGroup(value_box, value_label, value_detail)
        value_group.next_to(key_group, RIGHT, buff=0.2)
        
        # Size annotation
        size_text = Text("72 bytes total", font_size=28, color=WHITE)
        size_text.next_to(key_group, DOWN, buff=0.5)
        
        # Ratio annotation
        ratio_text = Text("8:1 key/value ratio", font_size=24, color=ORANGE)
        ratio_text.next_to(size_text, DOWN, buff=0.3)
        
        self.play(
            Create(key_box),
            Write(key_label),
            Write(key_detail)
        )
        self.play(
            Create(value_box),
            Write(value_label),
            Write(value_detail)
        )
        self.play(Write(size_text))
        self.play(Write(ratio_text))
        self.wait(1)
        
        # Store for later
        self.data_structure = VGroup(
            section_title, key_group, value_group, size_text, ratio_text
        )
        
        self.play(FadeOut(self.data_structure))
    
    def demonstrate_compression_failure(self):
        """Animate why LZ4 compression fails on high-entropy data"""
        section_title = Text("2. Compression Test", font_size=36, color=YELLOW)
        section_title.to_edge(UP)
        self.play(Write(section_title))
        
        # Show hash key
        hash_text = Text(
            "a1b2c3d4e5f6...",
            font_size=32,
            font="monospace",
            color=RED
        )
        hash_label = Text("Hash Key (high entropy)", font_size=20, color=GRAY)
        hash_label.next_to(hash_text, DOWN)
        hash_group = VGroup(hash_text, hash_label)
        hash_group.shift(UP * 1.5)
        
        self.play(Write(hash_text))
        self.play(FadeIn(hash_label))
        
        # Show compression attempt
        arrow = Arrow(LEFT, RIGHT, color=BLUE)
        arrow.next_to(hash_group, DOWN, buff=0.5)
        lz4_label = Text("LZ4", font_size=24, color=BLUE)
        lz4_label.next_to(arrow, UP, buff=0.1)
        
        self.play(GrowArrow(arrow), Write(lz4_label))
        
        # Show compression result (same size)
        compressed_text = Text(
            "a1b2c3d4e5f6...",
            font_size=32,
            font="monospace",
            color=RED
        )
        compressed_label = Text("No compression! (1.0x)", font_size=24, color=ORANGE)
        compressed_label.next_to(compressed_text, DOWN)
        compressed_group = VGroup(compressed_text, compressed_label)
        compressed_group.next_to(arrow, DOWN, buff=0.5)
        
        self.play(Write(compressed_text))
        self.play(Write(compressed_label))
        self.wait(1)
        
        # Show contrast with JSON
        contrast = Text("vs JSON: 2-4x compression ✓", font_size=20, color=GREEN)
        contrast.next_to(compressed_group, DOWN, buff=0.5)
        self.play(FadeIn(contrast))
        self.wait(1)
        
        # Cleanup
        self.play(
            FadeOut(section_title),
            FadeOut(hash_group),
            FadeOut(arrow),
            FadeOut(lz4_label),
            FadeOut(compressed_group),
            FadeOut(contrast)
        )
    
    def build_overhead_stack(self):
        """Build up the overhead components as a stacked bar chart with improved labels"""
        section_title = Text("3. Overhead Breakdown", font_size=36, color=YELLOW)
        section_title.to_edge(UP)
        self.play(Write(section_title))
        
        # Create axes
        ax = Axes(
            x_range=[0, 1.4, 0.2],
            y_range=[0, 1, 1],
            x_length=10,
            y_length=1,
            axis_config={"include_tip": False},
            x_axis_config={"numbers_to_include": np.arange(0, 1.5, 0.2)},
        )
        ax.shift(DOWN * 0.5)
        
        x_label = Text("Storage Multiplier", font_size=20)
        x_label.next_to(ax, DOWN)
        
        # Component data with short names for bars and full names for legend
        components = [
            {"short": "Raw\nData", "full": "Raw Data", "value": 1.0, "color": BLUE, "pct": "1.0x"},
            {"short": "B", "full": "Bloom Filter", "value": 0.017, "color": GREEN, "pct": "1.7%"},
            {"short": "I", "full": "Index Blocks", "value": 0.064, "color": YELLOW, "pct": "6.4%"},
            {"short": "M", "full": "Block Meta", "value": 0.016, "color": PURPLE, "pct": "1.6%"},
            {"short": "Univ\nComp", "full": "Universal Compaction", "value": 0.20, "color": RED, "pct": "20%"},
            {"short": "F", "full": "Fragment", "value": 0.038, "color": ORANGE, "pct": "3.8%"},
        ]
        
        # Build bars incrementally
        current_x = 0
        bars = VGroup()
        bar_labels = VGroup()
        
        # Legend position (top right)
        legend_start_y = 2.5
        legend_items = VGroup()
        
        for i, comp in enumerate(components):
            # Create bar
            bar_width = comp["value"] * (10/1.4)  # Scale to axis
            bar = Rectangle(
                width=bar_width,
                height=1.5,
                fill_opacity=0.8,
                fill_color=comp["color"],
                stroke_color=WHITE,
                stroke_width=2
            )
            bar.move_to(ax.c2p(current_x + comp["value"]/2, 0.5))
            
            # Create label - smart placement based on bar width
            if bar_width > 0.5:  # Wide enough for text inside
                label_text = Text(comp["short"], font_size=14, color=WHITE)
                label_text.move_to(bar.get_center())
            else:  # Too narrow - put label above with line
                label_text = Text(comp["short"], font_size=12, color=comp["color"])
                label_text.move_to(bar.get_top() + UP * 0.5)
                # Add connecting line
                line = Line(
                    bar.get_top(),
                    label_text.get_bottom(),
                    color=comp["color"],
                    stroke_width=1
                )
                label_text = VGroup(line, label_text)
            
            # Create legend entry
            legend_box = Rectangle(
                width=0.3,
                height=0.2,
                fill_opacity=0.8,
                fill_color=comp["color"],
                stroke_color=WHITE
            )
            legend_text = Text(
                f"{comp['full']} ({comp['pct']})",
                font_size=16,
                color=WHITE
            )
            legend_text.next_to(legend_box, RIGHT, buff=0.2)
            legend_entry = VGroup(legend_box, legend_text)
            legend_entry.to_edge(RIGHT, buff=0.5)
            legend_entry.shift(UP * (legend_start_y - i * 0.5))
            
            # Animate
            if i == 0:
                self.play(
                    Create(ax),
                    Write(x_label),
                    FadeIn(bar),
                    Write(label_text) if isinstance(label_text, Text) else Create(label_text),
                    FadeIn(legend_entry)
                )
            else:
                self.play(
                    FadeIn(bar),
                    Write(label_text) if isinstance(label_text, Text) else Create(label_text),
                    FadeIn(legend_entry),
                    run_time=0.8
                )
            
            bars.add(bar)
            bar_labels.add(label_text)
            legend_items.add(legend_entry)
            current_x += comp["value"]
            
            # Show running total below the bars
            total = sum(c["value"] for c in components[:i+1])
            total_text = Text(f"Total: {total:.3f}x", font_size=24, color=YELLOW)
            total_text.next_to(ax, DOWN, buff=1.5)
            
            if i > 0:
                self.play(Transform(self.running_total, total_text))
            else:
                self.running_total = total_text
                self.play(Write(self.running_total))
            
            self.wait(0.3)
        
        self.wait(1)
        
        # Store for final scene
        self.overhead_bars = VGroup(ax, x_label, bars, bar_labels, self.running_total)
        self.legend_items = legend_items
        
        self.play(FadeOut(section_title))
    
    def show_final_result(self):
        """Show the final validation"""
        # Move bars and legend up
        self.play(
            self.overhead_bars.animate.scale(0.6).to_edge(UP, buff=1),
            self.legend_items.animate.scale(0.6).to_edge(UP, buff=1).shift(RIGHT * 2)
        )
        
        # Show comparison
        result_title = Text("4. Validation", font_size=36, color=YELLOW)
        result_title.next_to(self.overhead_bars, DOWN, buff=0.5)
        self.play(Write(result_title))
        
        # Create comparison table
        table_data = [
            ["Source", "Overhead", "Match"],
            ["Calculation", "1.33x", "✓"],
            ["Document", "1.30x", "✓"],
            ["Facebook Research", "1.3-2.0x", "✓"],
            ["Industry Benchmarks", "1.3-1.4x", "✓"],
        ]
        
        table = Table(
            table_data,
            include_outer_lines=True,
            line_config={"stroke_width": 1, "color": BLUE}
        )
        table.scale(0.5)
        table.next_to(result_title, DOWN, buff=0.5)
        
        # Color the header row
        for cell in table.get_rows()[0]:
            cell.set_fill(BLUE, opacity=0.3)
        
        # Color the checkmarks
        for i in range(1, 5):
            table.get_rows()[i][2].set_color(GREEN)
        
        self.play(Create(table))
        self.wait(1)
        
        # Final conclusion
        conclusion = Text(
            "x1.3 overhead is JUSTIFIED ✓",
            font_size=40,
            color=GREEN,
            weight=BOLD
        )
        conclusion.next_to(table, DOWN, buff=0.5)
        
        self.play(Write(conclusion))
        
        # Add sparkles effect
        stars = VGroup(*[
            Star(color=YELLOW, fill_opacity=0.8).scale(0.2).move_to(
                conclusion.get_center() + 
                np.array([np.random.uniform(-3, 3), np.random.uniform(-1, 1), 0])
            )
            for _ in range(20)
        ])
        
        self.play(
            LaggedStart(*[
                FadeIn(star, scale=0.5)
                for star in stars
            ], lag_ratio=0.1)
        )
        self.play(
            LaggedStart(*[
                FadeOut(star, scale=2)
                for star in stars
            ], lag_ratio=0.05)
        )


class OverheadComparison(Scene):
    """Bonus scene: Compare different workloads"""
    
    def construct(self):
        title = Text("Overhead Comparison", font_size=40, color=BLUE)
        title.to_edge(UP)
        self.play(Write(title))
        
        # Create comparison bars
        workloads = [
            {"name": "Deduplication\n(high-entropy)", "overhead": 1.33, "color": RED},
            {"name": "Generic Web App\n(compressible)", "overhead": 1.15, "color": GREEN},
            {"name": "JSON Documents\n(high compression)", "overhead": 0.8, "color": BLUE},
        ]
        
        bars = VGroup()
        for i, wl in enumerate(workloads):
            # Bar
            bar = Rectangle(
                width=wl["overhead"] * 3,
                height=1,
                fill_opacity=0.8,
                fill_color=wl["color"],
                stroke_color=WHITE
            )
            bar.shift(DOWN * i * 1.5 + LEFT * (2 - wl["overhead"] * 1.5))
            
            # Label
            label = Text(wl["name"], font_size=20)
            label.next_to(bar, LEFT, buff=0.5)
            
            # Value
            value = Text(f"{wl['overhead']:.2f}x", font_size=24, color=YELLOW)
            value.next_to(bar, RIGHT, buff=0.2)
            
            group = VGroup(label, bar, value)
            bars.add(group)
        
        bars.move_to(ORIGIN)
        
        for bar in bars:
            self.play(
                FadeIn(bar[0]),  # label
                GrowFromEdge(bar[1], LEFT),  # bar
                Write(bar[2])  # value
            )
        
        # Highlight deduplication
        highlight = SurroundingRectangle(bars[0], color=YELLOW, buff=0.2)
        self.play(Create(highlight))
        
        note = Text(
            "High-entropy data + Universal Compaction\n→ Higher but justified overhead",
            font_size=20,
            color=YELLOW
        )
        note.next_to(bars, DOWN, buff=1)
        self.play(FadeIn(note))
        
        self.wait(2)


class KeyValueRatioImpact(Scene):
    """Bonus scene: Show how key/value ratio affects index overhead"""
    
    def construct(self):
        title = Text("Why Index Overhead is High", font_size=40, color=BLUE)
        title.to_edge(UP)
        self.play(Write(title))
        
        # Create two scenarios
        scenarios = [
            {
                "name": "Typical Web App",
                "key_size": 20,
                "value_size": 2000,
                "index_overhead": 0.2,
                "y_pos": 2
            },
            {
                "name": "Deduplication",
                "key_size": 64,
                "value_size": 8,
                "index_overhead": 6.4,
                "y_pos": -1
            }
        ]
        
        for scenario in scenarios:
            # Title
            name_text = Text(scenario["name"], font_size=28)
            name_text.shift(UP * scenario["y_pos"])
            self.play(Write(name_text))
            
            # Key and Value boxes (proportional)
            max_width = 8
            total_size = scenario["key_size"] + scenario["value_size"]
            key_width = (scenario["key_size"] / total_size) * max_width
            value_width = (scenario["value_size"] / total_size) * max_width
            
            key_box = Rectangle(width=key_width, height=0.8, fill_opacity=0.7, fill_color=RED)
            key_label = Text(f"Key: {scenario['key_size']}B", font_size=16)
            key_label.move_to(key_box)
            
            value_box = Rectangle(width=value_width, height=0.8, fill_opacity=0.7, fill_color=GREEN)
            value_label = Text(f"Value: {scenario['value_size']}B", font_size=16)
            value_label.move_to(value_box)
            
            key_box.shift(UP * (scenario["y_pos"] - 0.6) + LEFT * (max_width/2 - key_width/2))
            value_box.next_to(key_box, RIGHT, buff=0)
            
            self.play(
                FadeIn(key_box),
                Write(key_label)
            )
            self.play(
                FadeIn(value_box),
                Write(value_label)
            )
            
            # Index overhead
            overhead_text = Text(
                f"Index Overhead: {scenario['index_overhead']}%",
                font_size=24,
                color=YELLOW if scenario['index_overhead'] > 1 else GREEN
            )
            overhead_text.next_to(value_box, DOWN, buff=0.3)
            self.play(Write(overhead_text))
            
            self.wait(0.5)
        
        # Explanation
        explanation = Text(
            "Same index cost ÷ Smaller values = Higher overhead %",
            font_size=24,
            color=ORANGE
        )
        explanation.to_edge(DOWN, buff=1)
        self.play(FadeIn(explanation))
        
        self.wait(2)
