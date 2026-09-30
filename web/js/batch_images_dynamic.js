import { app } from "../../scripts/app.js";

/**
 * Batch Images (跳过None) 的动态输入扩展。
 *
 * 行为：与内置 Batch Images 一致——最后一个输入端口一旦被连接，
 * 就自动追加一个新的 image_N 端口；空闲的尾部端口会自动回收。
 */

const NODE_NAME = "EasyBatchImages";
const MIN_INPUTS = 2;

function inputIndex(name) {
    const m = /^image_(\d+)$/.exec(name || "");
    return m ? parseInt(m[1], 10) : -1;
}

/** 保持 image_1..image_N 的连续编号，并按需增删端口 */
function syncInputs(node) {
    if (!node || !node.inputs) return;

    let maxConnected = 0;
    for (const inp of node.inputs) {
        const idx = inputIndex(inp.name);
        if (idx > 0 && inp.link != null) maxConnected = Math.max(maxConnected, idx);
    }

    // 目标数量：已连接的最大编号 + 1 个空位，且不少于 MIN_INPUTS
    const target = Math.max(MIN_INPUTS, maxConnected + 1);

    // 删除多余的空闲端口（从尾部开始）
    for (let i = node.inputs.length - 1; i >= 0; i--) {
        const inp = node.inputs[i];
        const idx = inputIndex(inp.name);
        if (idx < 0) continue;
        const isTail = idx > target;
        if (isTail && inp.link == null) {
            node.removeInput(i);
        }
    }

    // 追加缺失的端口
    const existing = new Set(node.inputs.map((i) => inputIndex(i.name)).filter((i) => i > 0));
    for (let i = 1; i <= target; i++) {
        if (!existing.has(i)) {
            node.addInput(`image_${i}`, "IMAGE");
        }
    }

    // 重排序，保证 image_1..image_N 顺序稳定
    const ordered = node.inputs
        .filter((inp) => inputIndex(inp.name) > 0)
        .sort((a, b) => inputIndex(a.name) - inputIndex(b.name));
    node.inputs = ordered;

    if (app.canvas) app.canvas.setDirty(true);
}

app.registerExtension({
    name: "EasyUI.BatchImagesDynamicInputs",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_NAME) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = onNodeCreated?.apply(this, arguments);
            // 初始化时保证最少端口数
            setTimeout(() => syncInputs(this), 0);
            return r;
        };

        const onConnectionsChange = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function (type, index, connected, link_info) {
            const r = onConnectionsChange?.apply(this, arguments);
            // type: 1 = INPUT
            if (type === 1) {
                syncInputs(this);
            }
            return r;
        };

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const r = onConfigure?.apply(this, arguments);
            setTimeout(() => syncInputs(this), 0);
            return r;
        };
    },
});
