# 上游依据

核对基准：TerraFirmaCraft tag `v4.2.12`，Minecraft 1.21.1，2026-10-24 检查。

- [ForgeStep.java](https://github.com/TerraFirmaCraft/TerraFirmaCraft/blob/v4.2.12/src/main/java/net/dries007/tfc/common/component/forge/ForgeStep.java)：8 种动作、位移、图标坐标。
- [ForgeRule.java](https://github.com/TerraFirmaCraft/TerraFirmaCraft/blob/v4.2.12/src/main/java/net/dries007/tfc/common/component/forge/ForgeRule.java)：三种击打共享 hit 类别；各位置条件独立匹配最后三步。
- [AnvilScreen.java](https://github.com/TerraFirmaCraft/TerraFirmaCraft/blob/v4.2.12/src/main/java/net/dries007/tfc/client/screen/AnvilScreen.java)：GUI atlas 与绘制坐标、红绿规则覆盖层、目标范围括号。
- [AnvilStepButton.java](https://github.com/TerraFirmaCraft/TerraFirmaCraft/blob/v4.2.12/src/main/java/net/dries007/tfc/client/screen/button/AnvilStepButton.java)：动作按钮 16×16，使用 atlas 的 y=240 一行；只在已定位、校验的按钮中心发送鼠标点击。
- [AnvilContainer.java](https://github.com/TerraFirmaCraft/TerraFirmaCraft/blob/v4.2.12/src/main/java/net/dries007/tfc/common/container/AnvilContainer.java)：主输入槽 `(22,76)`；容器物品 Shift 点击按游戏规则转入玩家背包。
- [Forging.java](https://github.com/TerraFirmaCraft/TerraFirmaCraft/blob/v4.2.12/src/main/java/net/dries007/tfc/common/component/forge/Forging.java)：历史列表与匹配时的方向。
- [AnvilBlockEntity.java](https://github.com/TerraFirmaCraft/TerraFirmaCraft/blob/v4.2.12/src/main/java/net/dries007/tfc/common/blockentities/AnvilBlockEntity.java)：仅 work < 0 或 work > 150 会越界；未加工坯料在 0 处的负向操作被忽略。
- [AnvilRecipe.java](https://github.com/TerraFirmaCraft/TerraFirmaCraft/blob/v4.2.12/src/main/java/net/dries007/tfc/common/recipes/AnvilRecipe.java)：目标容差为含边界的范围。
- [ServerConfig.java](https://github.com/TerraFirmaCraft/TerraFirmaCraft/blob/v4.2.12/src/main/java/net/dries007/tfc/config/ServerConfig.java)：anvilAcceptableWorkRange 默认为 0。

逻辑 GUI 大小 176×207；current 指针左上角为 `(11 + work,104)`，target 为 `(11 + target,98)`；不是把整条进度条按比例猜测为 0–150。

规则图标位于 `(61+i*19,13)`，16×16；顺序覆盖层位于 `(59+i*19,13)`，20×22。覆盖层宽度比槽距多 1 像素，因此识别忽略相邻槽的重叠边列。历史从 x=99 开始向左绘制，源列表由旧到新；历史第一行与规则覆盖层底部重叠，识别时排除该行。

默认 atlas 在 y=224 的 light / medium / hard 三个历史图标像素完全相同。识别按 hit 类别合并候选，不推断历史力度；solver 的历史状态本就只需要动作类别。y=240 的实际按钮仍分别匹配，执行后用 current 位移验证真实力度。

批量使用主输入槽限量 1 的行为，取起原料堆叠后点入一件，再放回余料。`AnvilBlockEntity.setAndUpdateSlots` 会优先自动选唯一配方，或复用 `lastRecipe`；工具仍要求首件选好并校验后续配方。成品替换主输入槽物品，完成后经过成品图标验证再 Shift 转出。堆叠数字可由资源包字体绘制到第 7 像素行，物品比较与定位边线都避开数字区。

模板从用户本地 JAR / 已启用资源包即时构造。源码只作行为参考，未复制上游 Java 实现或将贴图纳入分发包。上游源码及美术资产仍按各自许可证归属。
