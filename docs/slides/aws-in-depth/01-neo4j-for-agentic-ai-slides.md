---
marp: true
theme: default
paginate: true
---

<style>
section {
  --marp-auto-scaling-code: false;
}

li {
  opacity: 1 !important;
  animation: none !important;
  visibility: visible !important;
}

/* Disable all fragment animations */
.marp-fragment {
  opacity: 1 !important;
  visibility: visible !important;
}

ul > li,
ol > li {
  opacity: 1 !important;
}
</style>

## The ReAct (Reasoning + Acting) Loop

- **Receive**: take in the question, history, and tool descriptions
- **Reason**: analyze the question and decide what to do
- **Act**: execute the selected tool
- **Observe**: read the tool's result
- **Respond**: return the answer in natural language
