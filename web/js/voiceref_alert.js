import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// 监听后端 voiceref.alert 事件，在界面上弹出告警（不进入输出文本）
app.registerExtension({
    name: "VoiceRefDescription.Alert",
    setup() {
        api.addEventListener("voiceref.alert", (event) => {
            const detail = event.detail || {};
            const message = detail.message || "";
            const title = detail.title || "音色参考音频告警";

            // 节点本体显示红色标记
            const nodeId = detail.node_id;
            if (nodeId !== undefined) {
                const node = app.graph.getNodeById(Number(nodeId));
                if (node) {
                    node.bgcolor = "#9b1c1c";
                    node.hasErrors = true;
                    if (app.canvas) app.canvas.setDirty(true);
                }
            }

            // 弹窗提示
            window.alert(`${title}\n\n${message}`);
            console.warn(`[${title}] ${message}`);
        });
    },
});
