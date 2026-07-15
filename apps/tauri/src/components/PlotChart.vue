<script setup lang="ts">
// Thin Plotly wrapper: recessive chrome, unified hover, theme-aware.
import Plotly, { type Layout, type PlotData } from "plotly.js-basic-dist-min";
import { onBeforeUnmount, onMounted, ref, watch } from "vue";

const props = defineProps<{
  traces: Partial<PlotData>[];
  layout?: Partial<Layout>;
  dark: boolean;
}>();

const el = ref<HTMLDivElement | null>(null);

function chrome(dark: boolean): Partial<Layout> {
  const grid = dark ? "#2c2c2a" : "#e1e0d9";
  const axis = dark ? "#383835" : "#c3c2b7";
  return {
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: { family: 'system-ui, -apple-system, "Segoe UI", sans-serif', size: 12, color: "#898781" },
    margin: { l: 48, r: 8, t: 8, b: 36 },
    xaxis: { gridcolor: grid, linecolor: axis, zerolinecolor: axis, fixedrange: true },
    yaxis: { gridcolor: grid, linecolor: axis, zerolinecolor: axis, fixedrange: true, rangemode: "tozero" },
    hovermode: "x unified",
    hoverlabel: {
      bgcolor: dark ? "#1a1a19" : "#fcfcfb",
      bordercolor: dark ? "#383835" : "#c3c2b7",
      font: { color: dark ? "#ffffff" : "#0b0b0b" },
    },
    showlegend: false, // single-series charts: the card title names the series
  };
}

function render() {
  if (!el.value) return;
  Plotly.react(el.value, props.traces, { ...chrome(props.dark), ...props.layout }, {
    displayModeBar: false,
    responsive: true,
  });
}

onMounted(render);
watch(() => [props.traces, props.dark, props.layout], render, { deep: true });
onBeforeUnmount(() => {
  if (el.value) Plotly.purge(el.value);
});
</script>

<template>
  <div ref="el" class="plot"></div>
</template>

<style scoped>
.plot {
  width: 100%;
  height: 260px;
}
</style>
