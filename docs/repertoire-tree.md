# 共享前缀的分支 HTML 渲染组件

`web/repertoire-training/tree-view.js` 从棋谱屋当前界面的三个函数按 UTF-8 原始字节范围提取：`esc`、`routeNode`、`treeHtml`。函数内容没有重写；文件只加了 strict mode、说明和 CommonJS 导出。完整源文件 SHA256、三个半开字节区间及组件 SHA256 见 `manual-repertoire-provenance.json`。

```js
const E = require('../web/repertoire-training/editor-model.js');
const {treeHtml} = require('../web/repertoire-training/tree-view.js');

const collapsed = new Set(); // 存放使用者手动折叠的节点 ID
const html = treeHtml(view, E, 'included', collapsed);
```

`view` 来自已校验的录谱模型：`root_id`、`goal_plies` 和 `nodes`；每个节点有独立的 `id`、`parent_id`、整数 `ply`、`name` 或 `move`、`enabled`，可有 `terminal`。输入应是合法无环树。`E` 注入已公开控制器中的 `routes(view, filter)`；组件没有偷偷加载网站、数据库或引擎。`filter` 可选 `included` 或 `all`。

共同前缀只渲染一次，同一父局面的备选着法放在同一个 `tree-fork` 列表中，各自有 `tree-option` 外层。该选择的后继位于自己的 `tree-option-body`，不会和下一个同级选择混成一列。每次分叉分别标出 `1/2`、`2/2` 等序号。具有相同名称但父节点不同的路径仍分开保留，不按名字或棋盘猜测合并。

`collapsed` 由宿主界面维护。折叠只给后续容器加 `hidden`，后继 HTML 和节点身份仍保留，输入模型也不会被修改。按已纳入路线筛选时，到达已纳入后继所需的未选前缀仍显示为草稿；显示不等于自动纳入训练。

返回值仅是 HTML 字符串，含节点、纳入复选框和折叠按钮所需的 `data-*` 属性。宿主负责 CSS、点击事件、保存、焦点、滚动和业务校验。本组件不附带完整产品界面、样式或后端，也不证明棋步优劣。名称与节点标识通过原函数的 HTML 转义；数值等字段仍依赖上面的模型契约。

```bash
node --test tests/tree-view.test.cjs
```

测试只有人工构造的节点、名称和纳入状态，验证共享前缀、同级外层、后继嵌套、独立序号、手动折叠、草稿前缀、不同父节点的同名着法和转义，不含真实棋史或个人训练资料。
