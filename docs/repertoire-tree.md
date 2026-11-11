# 共享前缀的紧凑树与卡片 HTML 渲染组件

`web/repertoire-training/tree-view.js` 从棋谱屋当前界面的五个函数按 UTF-8 原始字节范围提取：`esc`、`routeNode`、`treeTopology`、`diagramHtml`、`treeHtml`。函数内容没有重写；文件只加了 strict mode、说明和 CommonJS 导出。完整源文件 SHA256、五个半开字节区间及组件 SHA256 见 `manual-repertoire-provenance.json`。渲染入口为`treeHtml`和`diagramHtml`，保留之前导出的`esc`、`routeNode`以兼容既有调用；`treeTopology`作为内部辅助函数。

```js
const E = require('../web/repertoire-training/editor-model.js');
const {treeHtml, diagramHtml} = require('../web/repertoire-training/tree-view.js');

const collapsed = new Set(); // 存放使用者手动折叠的节点 ID
const compactHtml = treeHtml(view, E, 'included', collapsed);
const cardHtml = diagramHtml(view, E, 'included', collapsed);
```

`view` 来自已校验的录谱模型：`root_id`、`goal_plies` 和 `nodes`；每个节点有独立的 `id`、`parent_id`、整数 `ply`、`name` 或 `move`、`enabled`，可有 `terminal`。输入应是合法无环树。`E` 注入已公开控制器中的 `routes(view, filter)`；组件没有偷偷加载网站、数据库或引擎。`filter` 可选 `included` 或 `all`。

共同前缀只渲染一次，同一父局面的备选着法放在同一个 `tree-fork` 列表中，各自有 `tree-option` 外层。该选择的后继位于自己的 `tree-option-body`，不会和下一个同级选择混成一列。每次分叉分别标出 `1/2`、`2/2` 等序号。具有相同名称但父节点不同的路径仍分开保留，不按名字或棋盘猜测合并。

`treeHtml`适合紧凑纵向列表；`diagramHtml`提供完整线路卡片图的 HTML 结构，共同前缀仍只出现一次，到分叉再产生同级卡片。卡片后继放在所属`diagram-step`的`diagram-children`中，另一条同级线路不会重复抄一遍前缀。宿主可以保留两种显示入口，让使用者选择样式，而不改变录谱数据。

两个入口共用内部`treeTopology(view, E, filter)`，采用相同的节点筛选与后继计数。因此切换样式时，已纳入/全部草稿范围、原节点身份和手动折叠集合一致。改变的是 HTML 展示结构，既不合并不同来路，也不复制训练选择。

`collapsed` 由宿主界面维护。折叠只给后续容器加 `hidden`，后继 HTML 和节点身份仍保留，输入模型也不会被修改。按已纳入路线筛选时，到达已纳入后继所需的未选前缀仍显示为草稿；显示不等于自动纳入训练。

返回值仅是 HTML 字符串，含节点、纳入复选框和折叠按钮所需的 `data-*` 属性。宿主负责 CSS、点击事件、保存、焦点、滚动和业务校验；紧凑列表使用`tree-*`类，卡片结构使用`diagram-*`类，卡片的横向并列、连线和紧凑树的缩进均须宿主提供 CSS。本组件不附带完整产品界面、样式或后端，也不证明棋步优劣。名称与节点标识通过原函数的 HTML 转义；数值等字段仍依赖上面的模型契约。

```bash
node --test tests/tree-view.test.cjs
```

测试只有人工构造的节点、名称和纳入状态，保留紧凑树的八项结构检查，再验证卡片共享前缀、同级与后继、折叠保留、两种渲染结果的筛选集合一致，以及卡片中的 HTML 转义，不含真实棋史或个人训练资料。HTML 结构测试不替代宿主 CSS 的浏览器验收。
