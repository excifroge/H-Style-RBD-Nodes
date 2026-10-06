# H-Style RBD Nodes：Blender 几何节点用的刚体破碎节点

[![license](https://img.shields.io/badge/license-GPL--3.0--or--later-green.svg)](#许可证)
[![blender](https://img.shields.io/badge/Blender-5.2%20LTS-green.svg)](#环境要求)

**文档** ([English](README.md), [日本語](README_JA.md), [中文](README_ZH.md))

*H-Style RBD Nodes* 是一组用于 Blender 几何节点 (Geometry Nodes) 的刚体破碎节点，节点的命名、输入输出和参数分组采用 H-Style。  
把模型接进 `RBD Material Fracture`，得到碎块、约束、碰撞代理三路数据，一路接到 `RBD Bullet Solver`，烘焙到时间线，再导出到游戏引擎。面向游戏特效里的模型动画：破碎、爆炸、地裂。

**核心特点**

* **H-Style 的节点**：一个功能一个节点，节点之间用属性传递数据，可以在中间插入自己的节点
* **烘焙到时间线**：解算使用 Blender 自带的 Bullet，结果存在节点上，之后拖动时间线不再重新解算
* **面向游戏引擎**：导出骨骼 FBX、刚体 VAT、Alembic，另提供 Unity (URP) 用的着色器和播放组件

主要功能包括 Concrete / Glass / Wood 三种破碎方式、把现成零件当作碎块、按接触关系建立约束、分簇、初速度、延迟激活、Blender 力场，以及多个物体在同一个世界里解算。  
本扩展只包含 Python 代码，不修改 Blender，不带二进制文件；节点组在第一次使用时生成。

| 撞墙 | 地裂 | 爆炸 |
|---|---|---|
| ![](Docs/Images/01_wall_smash.gif) | ![](Docs/Images/02_ground_crack.gif) | ![](Docs/Images/03_explosion.gif) |

| 玻璃 | 木柱 | 砖墙（现成零件） |
|---|---|---|
| ![](Docs/Images/04_glass.gif) | ![](Docs/Images/05_wood_post.gif) | ![](Docs/Images/06_brick_wall.gif) |

各节点的详细说明请参阅下文。

> **本项目对 AI 友好。** 我为你准备了一份交接文档 [AGENTS.md](AGENTS.md)（英文）：把它交给你自己的 AI 阅读，就可以让 AI 为你讲解这个扩展，并自行修改它。

## 目录

<details>
<summary>详细</summary>

- [设置](#设置)
    - [环境要求](#环境要求)
    - [安装](#安装)
- [使用方法](#使用方法)
    - [新建 RBD 网络](#新建-rbd-网络)
    - [调整参数](#调整参数)
    - [添加节点](#添加节点)
    - [烘焙](#烘焙)
- [节点](#节点)
    - [三路数据](#三路数据)
    - [RBD Material Fracture](#rbd-material-fracture)
    - [RBD Assemble](#rbd-assemble)
    - [RBD Constraints From Rules](#rbd-constraints-from-rules)
    - [RBD Configure](#rbd-configure)
    - [RBD Select](#rbd-select)
    - [RBD Constraint Properties](#rbd-constraint-properties)
    - [RBD Cluster](#rbd-cluster)
    - [RBD Exploded View](#rbd-exploded-view)
    - [RBD Bullet Solver](#rbd-bullet-solver)
- [属性](#属性)
- [初速度与力场](#初速度与力场)
- [多个物体一起解算](#多个物体一起解算)
- [导出](#导出)
    - [在 Unity 中使用](#在-unity-中使用)
    - [VAT 格式](#vat-格式)
- [示例](#示例)
- [限制](#限制)
- [商标](#商标)
- [许可证](#许可证)

</details>

## 设置

#### 环境要求
本扩展支持以下环境。

* Blender 5.2 LTS 及以上

配合 VAT 导出使用的 Unity 着色器和播放组件在以下环境中核对过。

* Unity 6 (6000.0 LTS)
* Universal Render Pipeline 17

#### 安装
有两种安装方式，任选其一。

**方式一：拖进 Blender**

把下面的链接从浏览器拖到 Blender 的窗口里，按提示确认。

**[➜ 将此链接拖入 Blender 安装](https://raw.githubusercontent.com/excifroge/H-Style-RBD-Nodes/main/Repository/h_style_rbd_nodes.zip?repository=.%2Findex.json&blender_version_min=5.2.0)**

* 需要先在 **Edit > Preferences > System > Network** 中启用 **Allow Online Access**
* 第一次拖入时，Blender 会询问是否添加本扩展的仓库，确认后开始安装。此后有新版本时，可以在 **Edit > Preferences > Get Extensions** 中更新
* 这个链接只用于拖动，点击它只会下载 zip

**方式二：从 zip 安装**

1. 在 [Releases](https://github.com/excifroge/H-Style-RBD-Nodes/releases) 页面下载 `h_style_rbd_nodes-x.y.z.zip`，不要解压
2. 在 Blender 中打开 **Edit > Preferences > Get Extensions**，从右上角的下拉菜单中选择 **Install from Disk**，选中下载的 zip；也可以把下载好的 zip 文件直接拖进 Blender 的窗口

用任一方式安装后，在 3D 视图中按 `N` 打开侧栏，确认出现 **H-Style RBD** 标签页。

安装后，几何节点编辑器的 **Add** 菜单中会多出 **RBD** 子菜单。

本文档的截图和参数名均以英文界面为准。  
节点的名字在任何语言下都不翻译；Blender 的语言设置为简体中文时，参数名会显示为中文，对应的中文名写在各表格“说明”一栏的开头。

## 使用方法

#### 新建 RBD 网络
选中一个封闭的网格物体，在侧栏的 **H-Style RBD** 标签页中点击 **Fracture This Object**（破碎这个物体）。

物体上会添加一个几何节点修改器，其中 `RBD Material Fracture` 和 `RBD Bullet Solver` 两个节点已经连好。

<p align="center">
  <img width="80%" src="Docs/Images/node_network.png" alt="RBD Network"><br>
  <font color="grey">新建的 RBD 网络</font>
</p>

模型本身已经做成一块块零件（砖墙、木板）时，改为点击 **Use Its Loose Parts**（用它现成的零件）。  
这时得到的是 `RBD Assemble`、`RBD Constraints From Rules`、`RBD Bullet Solver` 三个节点。

#### 调整参数
各 RBD 节点的参数既可以在节点上设置，也可以在侧栏中设置，两处是同一份数据。

<p align="center">
  <img width="45%" src="Docs/Images/ui_sidebar.png" alt="Sidebar"><br>
  <font color="grey">侧栏中显示的节点参数</font>
</p>

位置类的参数（Impact Point、Origin、Wave Origin、Center）下方有 **Impact Point from 3D Cursor** 这样的按钮，可以把 3D 游标的位置换算到物体自身空间后填入。

#### 添加节点
在几何节点编辑器中选择 **Add > RBD**，把节点拖到已有节点之间的连线上。  
RBD 节点之间需要连接 [三路数据](#三路数据)。

#### 烘焙
点击侧栏底部的 **Bake**（烘焙）。

Bullet 无法在几何节点求值的过程中运行，因此 `RBD Bullet Solver` 节点本身不进行解算。  
烘焙完成后，解算结果保存在该节点上，节点从此输出烘焙好的运动。之后修改上游节点的参数不会改变画面，需要再次点击 **Re-Bake**（重新烘焙）；点击垃圾桶图标 **Free Bake**（释放烘焙） 则回到实时的破碎结果。

烘焙之后可以进行以下操作。

* 拖动时间线：不会重新解算，上游的破碎节点也不再求值
* 移动、旋转、缩放、复制物体：破碎动画整体跟随
* [导出](#导出)

烘焙失败时不会改动任何数据，之前的烘焙结果仍然可用。

## 节点
RBD 节点共 9 个，按数据流动的顺序说明如下。

#### 三路数据
按照 H-Style 的做法，各节点之间传递三路数据。

<table width="100%">
<thead>
<tr><td><b>接口</b></td><td><b>说明</b></td></tr>
</thead>
<tbody>
<tr><td><b>Geometry</b></td><td>
几何数据。碎块本身，即用于渲染的网格。
</td></tr>
<tr><td><b>Constraint Geometry</b></td><td>
约束几何。只包含边的网格。一条边表示一条胶合，两端位于它连接的两块碎块的中心。
</td></tr>
<tr><td><b>Proxy Geometry</b></td><td>
代理几何。参与碰撞的形状。解算时，每块碎块使用它在这一路中的点的凸包作为碰撞体。<br>
要使用更简单的碰撞形状时，修改这一路即可。
</td></tr>
</tbody>
</table>

#### RBD Material Fracture
把模型切成碎块，同时生成约束几何和代理几何。对应 H-Style 的同名节点。

<p align="center">
  <img width="30%" src="Docs/Images/Nodes/material_fracture_concrete.png" alt="RBD Material Fracture (Concrete)">
  <img width="30%" src="Docs/Images/Nodes/material_fracture_glass.png" alt="RBD Material Fracture (Glass)">
  <img width="30%" src="Docs/Images/Nodes/material_fracture_wood.png" alt="RBD Material Fracture (Wood)"><br>
  <font color="grey">Material Type 分别为 Concrete、Glass、Wood 时的 RBD Material Fracture</font>
</p>

当前 Material Type 用不到的参数会自动从节点上隐藏。

<table width="100%">
<thead>
<tr><td colspan="3"><b>输入</b></td><td><b>说明</b></td></tr>
</thead>
<tbody>
<tr><td colspan="3"><b>Geometry</b></td><td>
几何数据。要破碎的模型。需要是封闭的网格，详情请参阅<a href="#限制">限制</a>。
</td></tr>
<tr><td colspan="3"><b>Constraint Geometry</b> / <b>Proxy Geometry</b></td><td>
约束几何、代理几何。上游已有的约束和代理，与本节点新生成的合并后输出。可以不连接。
</td></tr>
<tr><td colspan="3"><b>Extra Points</b></td><td>
额外点。
<p>
可选。连接点云或网格。
</p>
<p>
<ul>
<li>Concrete、Wood: 使用这些点作为胞体的种子点，不再自动撒点</li>
<li>Glass: 第一个点作为冲击点</li>
</ul>
</p>
</td></tr>
<tr><td colspan="3"><b>Material Type</b></td><td>
材质类型。
<p>
破碎的方式，从以下选项中指定。
</p>
<p>
<ul>
<li>Concrete（混凝土）: 块状碎片，冲击点附近更碎（默认）</li>
<li>Glass（玻璃）: 围绕冲击点的放射裂纹和环形裂纹，直着切穿薄板</li>
<li>Wood（木纹）: 沿木纹方向的长条木刺</li>
</ul>
</p>
</td></tr>
<tr><td colspan="3"><b>Random Seed</b></td><td>
随机种。整个节点的随机种子。
</td></tr>
<tr><td colspan="3"><b>Impact Point</b></td><td>
冲击点。物体被击中的位置，在物体自身空间中指定。<br>
Glass 的裂纹从这里开始；Concrete 在这里碎得更细。
</td></tr>
<tr><td colspan="3"><b>Primary Fracture</b></td><td>
一级破碎。参数组。
</td></tr>
<tr><td></td><td colspan="2"><b>Scatter Points</b></td><td>
撒点数。
<p>
<b>仅在 Material Type 为 Concrete 或 Wood 时显示。</b>
</p>
<p>
种子点的数量，大约一个点对应一块碎块。默认值为 30。
</p>
</td></tr>
<tr><td></td><td colspan="2"><b>Scatter Seed</b></td><td>
撒点种子。只改变撒点的随机种子。
</td></tr>
<tr><td></td><td colspan="2"><b>Impact Bias</b></td><td>
冲击点集中度。
<p>
<b>仅在 Material Type 为 Concrete 时显示。</b>
</p>
<p>
集中在冲击点周围的种子点所占的比例。数值越大，冲击点附近越碎。
</p>
</td></tr>
<tr><td></td><td colspan="2"><b>Impact Radius</b></td><td>
冲击半径。
<p>
<b>仅在 Material Type 为 Concrete 时显示。</b>
</p>
<p>
上述种子点集中的范围。
</p>
</td></tr>
<tr><td></td><td colspan="2"><b>Cut Through</b></td><td>
透切。
<p>
<b>仅在 Material Type 为 Concrete 时显示。</b>
</p>
<p>
每一刀都沿模型最薄的方向直着切穿。用于地面、薄板和从正面看的墙。
</p>
</td></tr>
<tr><td colspan="3"><b>Secondary Fracture</b></td><td>
二级破碎。
<p>
<b>仅在 Material Type 为 Concrete 时显示。</b>
</p>
<p>
参数组，带启用开关。把一部分碎块再切碎，得到大块夹小块的效果。
</p>
</td></tr>
<tr><td></td><td colspan="2"><b>Fracture Ratio</b></td><td>
破碎比例。被再次切碎的碎块所占的比例。
</td></tr>
<tr><td></td><td colspan="2"><b>Points per Piece</b></td><td>
每块撒点数。在每块被再次切碎的碎块中追加的种子点数量。<br>
最终的碎块数约为 Scatter Points ×（1 + Fracture Ratio × Points per Piece）。
</td></tr>
<tr><td colspan="3"><b>Cracks</b></td><td>
裂纹。
<p>
<b>仅在 Material Type 为 Glass 时显示。</b>
</p>
<p>
参数组。
</p>
</td></tr>
<tr><td></td><td colspan="2"><b>Radial Crack Number</b></td><td>
放射裂纹数。从冲击点向外延伸的裂纹数量。
</td></tr>
<tr><td></td><td colspan="2"><b>Concentric Crack Number</b></td><td>
环形裂纹数。围绕冲击点的环形裂纹的圈数。
</td></tr>
<tr><td></td><td colspan="2"><b>Impact Spread</b></td><td>
冲击范围。环形裂纹距离冲击点最远的位置。
</td></tr>
<tr><td colspan="3"><b>Grain</b></td><td>
木纹方向。
<p>
<b>仅在 Material Type 为 Wood 时显示。</b>
</p>
<p>
参数组。
</p>
</td></tr>
<tr><td></td><td colspan="2"><b>Fracture Direction</b></td><td>
破碎方向。
<p>
木纹的方向。
</p>
<p>
<ul>
<li>Auto（自动）: 模型最长的一边（默认）</li>
<li>X / Y / Z: 指定的轴</li>
</ul>
</p>
</td></tr>
<tr><td></td><td colspan="2"><b>Splinter Length</b></td><td>
木刺长度。木刺的长度是宽度的多少倍。
</td></tr>
<tr><td colspan="3"><b>Detail</b></td><td>
细节。参数组，带启用开关。给切面加上凹凸。
</td></tr>
<tr><td></td><td colspan="2"><b>Detail Level</b></td><td>
细分级别。切面的细分次数。每增加一级，切面的面数变为 4 倍；用于游戏引擎时建议设置为 1。
</td></tr>
<tr><td></td><td colspan="2"><b>Noise Amplitude</b> / <b>Frequency</b></td><td>
噪波幅度、频率。凹凸的高度和疏密。
</td></tr>
<tr><td></td><td colspan="2"><b>Edge Fade</b></td><td>
边缘衰减。凹凸在距离模型原表面这么远的范围内逐渐消失，使外表面保持闭合。
</td></tr>
<tr><td colspan="3"><b>Constraints</b></td><td>
约束。参数组，带启用开关。启用时，在共享切面的相邻碎块之间生成约束。
</td></tr>
<tr><td></td><td colspan="2"><b>Primary Strength</b></td><td>
一级强度。胶合的强度。冲击超过此强度时胶合断开。
</td></tr>
<tr><td></td><td colspan="2"><b>Strength Variance</b></td><td>
强度随机。强度的随机变化幅度。
</td></tr>
<tr><td></td><td colspan="2"><b>Scale by Contact Area</b></td><td>
按接触面积缩放。启用时，共享切面较小的碎块之间胶合较弱。
</td></tr>
<tr><td colspan="3"><b>Output</b></td><td>
输出。参数组。
</td></tr>
<tr><td></td><td colspan="2"><b>Assign Inside Material</b> / <b>Inside Material</b></td><td>
指定内表面材质、内表面材质。为切面指定材质。
</td></tr>
<tr><td></td><td colspan="2"><b>UV Map</b> / <b>Inside UV Scale</b></td><td>
UV 贴图、内表面 UV 缩放。切面会得到盒式投影的 UV，写入这里指定的 UV 贴图。
</td></tr>
<tr><td></td><td colspan="2"><b>Robust Boolean</b></td><td>
稳健布尔。始终使用较慢的精确布尔。未启用时，只在快速布尔失败的碎块上自动改用精确布尔。
</td></tr>
<tr><td></td><td colspan="2"><b>Keep Vertex Group</b></td><td>
保留顶点组。
<p>
模型上的一个顶点组（或浮点属性）的名字。碎块会以相同的名字保留它，用于在下游选择碎块。
</p>
<p>
顶点组本身无法通过布尔运算保留，因此碎块的每个顶点取距离最近的原模型表面上的权重。
</p>
</td></tr>
</tbody>
</table>

模型原有的 UV、材质和顶点色会保留。  
碎块的外表面沿用原模型的着色法线，因此破碎后尚未移动时，外观与完整的模型相同，碎块之间没有接缝。

<table width="100%">
<thead>
<tr><td><b>输出</b></td><td><b>说明</b></td></tr>
</thead>
<tbody>
<tr><td><b>Geometry</b></td><td>几何数据。碎块。写入属性 <code>piece_id</code>、<code>inside</code>、<code>rbd_pivot</code>、<code>rbd_rest</code>。</td></tr>
<tr><td><b>Constraint Geometry</b></td><td>约束几何。约束。写入属性 <code>strength</code>、<code>area</code>、<code>anchor</code>。</td></tr>
<tr><td><b>Proxy Geometry</b></td><td>代理几何。不含切面凹凸的碎块。</td></tr>
</tbody>
</table>

#### RBD Assemble
不进行切割，把模型中每个独立的零件（连通块）作为一块碎块。对应 H-Style 的 Assemble。

用于已经做成零件的模型：砖墙、木板、手工切好的碎块。请先把所有零件合并为一个物体 (`Ctrl+J`)。

<p align="center">
  <img width="35%" src="Docs/Images/Nodes/assemble.png" alt="RBD Assemble"><br>
  <font color="grey">RBD Assemble</font>
</p>

本节点没有参数。零件原有的 UV、材质和顶点组保持不变。

<table width="100%">
<thead>
<tr><td><b>输出</b></td><td><b>说明</b></td></tr>
</thead>
<tbody>
<tr><td><b>Geometry</b></td><td>几何数据。碎块。写入属性 <code>piece_id</code>、<code>inside</code>、<code>rbd_pivot</code>、<code>rbd_rest</code>。</td></tr>
<tr><td><b>Constraint Geometry</b></td><td>约束几何。原样输出上游的约束。本节点不生成约束，请在后面连接 <a href="#rbd-constraints-from-rules">RBD Constraints From Rules</a>。</td></tr>
<tr><td><b>Proxy Geometry</b></td><td>代理几何。碎块本身。</td></tr>
</tbody>
</table>

#### RBD Constraints From Rules
在表面相互靠近的碎块之间生成约束。对应 H-Style 的同名节点。

可以用于任何来源的碎块。连接在 `RBD Material Fracture` 之后时，请关闭后者的 **Constraints**，否则会生成两份约束。

<p align="center">
  <img width="35%" src="Docs/Images/Nodes/constraints_from_rules.png" alt="RBD Constraints From Rules"><br>
  <font color="grey">RBD Constraints From Rules</font>
</p>

<table width="100%">
<thead>
<tr><td colspan="3"><b>输入</b></td><td><b>说明</b></td></tr>
</thead>
<tbody>
<tr><td colspan="3"><b>Search Radius</b></td><td>
搜索半径。表面之间的距离小于此值的碎块会被胶合在一起。默认值为 2 厘米。<br>
面与面贴合的零件可以直接识别；零件之间留有缝隙（例如砖缝）时，请设置为略大于缝隙的宽度。
</td></tr>
<tr><td colspan="3"><b>Strength</b> / <b>Strength Variance</b> / <b>Scale by Contact Area</b></td><td>
强度、强度随机、按接触面积缩放。与 <a href="#rbd-material-fracture">RBD Material Fracture</a> 的约束参数相同。
</td></tr>
<tr><td colspan="3"><b>Keep Incoming Constraints</b></td><td>
保留传入的约束。启用时，在上游已有的约束之外追加。禁用时替换上游的约束（默认）。
</td></tr>
<tr><td colspan="3"><b>Advanced</b></td><td>
高级。参数组。
</td></tr>
<tr><td></td><td colspan="2"><b>Samples per Piece</b></td><td>
每块采样点数。为寻找相邻的碎块，在每块碎块表面散布的点数。数值越大，越能识别较小的接触面。
</td></tr>
<tr><td></td><td colspan="2"><b>Seed</b></td><td>
随机种。散布点和强度随机使用的随机种子。
</td></tr>
</tbody>
</table>

#### RBD Configure
为选中的碎块写入属性：是否参与解算、初速度、激活时间和物理属性。对应 H-Style 的同名节点。

<p align="center">
  <img width="35%" src="Docs/Images/Nodes/configure.png" alt="RBD Configure"><br>
  <font color="grey">启用全部四个参数组时的 RBD Configure</font>
</p>

四个参数组各有一个启用开关，只有启用的参数组会写入属性。未被选中的碎块保持原有的值。  
可以串联多个 `RBD Configure`，分别设置不同的碎块。

<table width="100%">
<thead>
<tr><td colspan="3"><b>输入</b></td><td><b>说明</b></td></tr>
</thead>
<tbody>
<tr><td colspan="3"><b>Selection</b></td><td>
选中项。要设置的碎块。默认选中全部。<br>
可以连接 <a href="#rbd-select">RBD Select</a> 或任意布尔场。一块碎块的大部分顶点被选中时，视为选中。
</td></tr>
<tr><td colspan="3"><b>Set Active</b></td><td>
设置是否参与解算。参数组，带启用开关。写入属性 <code>active</code>。
</td></tr>
<tr><td></td><td colspan="2"><b>Active</b></td><td>
活动项。禁用时，选中的碎块始终不动，但其他碎块仍然会与它们碰撞。用于固定墙的底部或地面的外圈。
</td></tr>
<tr><td colspan="3"><b>Set Initial Velocity</b></td><td>
设置初速度。参数组，带启用开关。写入属性 <code>v</code> 和 <code>w</code>。详情请参阅<a href="#初速度与力场">初速度与力场</a>。
</td></tr>
<tr><td></td><td colspan="2"><b>Velocity Type</b></td><td>
速度类型。
<p>
<ul>
<li>Constant（常值）: 所有碎块使用相同的速度</li>
<li>Radial（径向）: 从原点向外，类似爆炸（默认）</li>
</ul>
</p>
</td></tr>
<tr><td></td><td colspan="2"><b>Velocity</b></td><td>
速度。
<p>
<b>仅在 Velocity Type 为 Constant 时显示。</b>
</p>
<p>
速度，单位为米/秒，方向在物体自身空间中指定。
</p>
</td></tr>
<tr><td></td><td colspan="2"><b>Origin</b></td><td>
原点。
<p>
<b>以下各项仅在 Velocity Type 为 Radial 时显示。</b>
</p>
<p>
爆炸的中心，在物体自身空间中指定。
</p>
</td></tr>
<tr><td></td><td colspan="2"><b>Speed</b></td><td>
速率。原点处的速度大小，单位为米/秒。
</td></tr>
<tr><td></td><td colspan="2"><b>Falloff Radius</b></td><td>
衰减半径。速度在此距离处衰减为 0。设置为 0 时不衰减。
</td></tr>
<tr><td></td><td colspan="2"><b>Up Bias</b></td><td>
向上偏移。速度方向向上偏转的程度。0 为正对远离原点的方向，1 为竖直向上。
</td></tr>
<tr><td></td><td colspan="2"><b>Speed Variance</b></td><td>
速度随机。速度大小的随机变化幅度。
</td></tr>
<tr><td></td><td colspan="2"><b>Spin</b></td><td>
翻滚。随机的旋转速度，单位为弧度/秒。
</td></tr>
<tr><td></td><td colspan="2"><b>Seed</b></td><td>
随机种。速度随机和翻滚使用的随机种子。
</td></tr>
<tr><td colspan="3"><b>Set Activation</b></td><td>
设置激活时间。参数组，带启用开关。写入属性 <code>activate_time</code>。<br>
碎块在激活之前保持不动，激活后才交给解算器。
</td></tr>
<tr><td></td><td colspan="2"><b>Activation Type</b></td><td>
激活方式。
<p>
<ul>
<li>At Time（定时）: 所有碎块在同一时刻激活</li>
<li>Radial Wave（径向波）: 按距离波的原点的远近依次激活（默认）</li>
</ul>
</p>
</td></tr>
<tr><td></td><td colspan="2"><b>Delay</b></td><td>
延迟。起始帧之后的秒数。
</td></tr>
<tr><td></td><td colspan="2"><b>Wave Origin</b> / <b>Wave Speed</b></td><td>
波的原点、波速。
<p>
<b>仅在 Activation Type 为 Radial Wave 时显示。</b>
</p>
<p>
波的中心（物体自身空间）和传播速度（米/秒）。
</p>
</td></tr>
<tr><td colspan="3"><b>Set Physical Properties</b></td><td>
设置物理属性。参数组，带启用开关。写入属性 <code>density</code>、<code>friction</code>、<code>bounce</code>。
</td></tr>
<tr><td></td><td colspan="2"><b>Density</b> / <b>Friction</b> / <b>Bounce</b></td><td>
密度、摩擦、回弹。未设置的碎块使用 <a href="#rbd-bullet-solver">RBD Bullet Solver</a> 上的值。
</td></tr>
</tbody>
</table>

#### RBD Select
输出一个选择（布尔场），连接到 `RBD Configure` 或 `RBD Constraint Properties` 的 **Selection**。相当于 H-Style 中按包围盒或属性建立的组。

<p align="center">
  <img width="24%" src="Docs/Images/Nodes/select_below_height.png" alt="RBD Select (Below Height)">
  <img width="24%" src="Docs/Images/Nodes/select_box.png" alt="RBD Select (Box)">
  <img width="24%" src="Docs/Images/Nodes/select_sphere.png" alt="RBD Select (Sphere)">
  <img width="24%" src="Docs/Images/Nodes/select_attribute.png" alt="RBD Select (Attribute)"><br>
  <font color="grey">Type 分别为 Below Height、Box、Sphere、Attribute 时的 RBD Select</font>
</p>

多个选择可以用 Blender 自带的布尔运算节点组合。

<table width="100%">
<thead>
<tr><td colspan="3"><b>输入</b></td><td><b>说明</b></td></tr>
</thead>
<tbody>
<tr><td colspan="3"><b>Type</b></td><td>
类型。
<p>
选择的方式，从以下选项中指定。位置均在物体自身空间中指定。
</p>
<p>
<ul>
<li>Below Height（低于高度）: 最低点不高于指定高度的碎块（默认）</li>
<li>Box（方框）: 中心位于方框内的碎块</li>
<li>Sphere（球形）: 中心位于球内的碎块</li>
<li>Attribute（属性）: 顶点组或属性的平均值不小于阈值的碎块</li>
</ul>
</p>
</td></tr>
<tr><td></td><td colspan="2"><b>Height</b></td><td>
高度。<b>仅在 Type 为 Below Height 时显示。</b>
</td></tr>
<tr><td></td><td colspan="2"><b>Center</b> / <b>Size</b></td><td>
中心、尺寸。<b>仅在 Type 为 Box 时显示。</b>Type 为 Sphere 时显示 <b>Center</b> 和 <b>Radius</b>（半径）。
</td></tr>
<tr><td></td><td colspan="2"><b>Attribute</b> / <b>Threshold</b></td><td>
属性、阈值。
<p>
<b>仅在 Type 为 Attribute 时显示。</b>
</p>
<p>
顶点组或属性的名字。用于破碎后的碎块时，请填写在 <code>RBD Material Fracture</code> 的 <b>Keep Vertex Group</b> 中指定的名字。
</p>
</td></tr>
<tr><td colspan="3"><b>Whole Pieces</b></td><td>
按整块。启用时按整块碎块判断（默认）。禁用时逐顶点判断。
</td></tr>
<tr><td colspan="3"><b>Invert</b></td><td>
反转。反转选择。
</td></tr>
</tbody>
</table>

#### RBD Constraint Properties
修改选中约束的强度。对应 H-Style 的同名节点。

<p align="center">
  <img width="35%" src="Docs/Images/Nodes/constraint_properties.png" alt="RBD Constraint Properties"><br>
  <font color="grey">RBD Constraint Properties</font>
</p>

<table width="100%">
<thead>
<tr><td colspan="3"><b>输入</b></td><td><b>说明</b></td></tr>
</thead>
<tbody>
<tr><td colspan="3"><b>Selection</b></td><td>
选中项。要修改的约束，在约束几何的边上求值。默认选中全部。
</td></tr>
<tr><td colspan="3"><b>Operation</b></td><td>
运算。
<p>
<ul>
<li>Set To（设为）: 把强度设置为指定的值（默认）</li>
<li>Multiply By（乘以）: 把原有的强度乘以指定的值</li>
</ul>
</p>
</td></tr>
<tr><td colspan="3"><b>Strength</b></td><td>
强度。用于上述运算的值。
</td></tr>
</tbody>
</table>

#### RBD Cluster
把碎块分成若干簇，簇内的胶合更强，破碎时得到大块带小块的效果。对应 H-Style 的同名节点。

<p align="center">
  <img width="35%" src="Docs/Images/Nodes/cluster.png" alt="RBD Cluster"><br>
  <font color="grey">RBD Cluster</font>
</p>

<table width="100%">
<thead>
<tr><td colspan="3"><b>输入</b></td><td><b>说明</b></td></tr>
</thead>
<tbody>
<tr><td colspan="3"><b>Size</b></td><td>
尺寸。一簇的大致尺寸。
</td></tr>
<tr><td colspan="3"><b>Jitter</b> / <b>Seed</b></td><td>
抖动、随机种。簇的形状的不规则程度和随机种子。
</td></tr>
<tr><td colspan="3"><b>Strength Scale</b></td><td>
强度倍数。簇内约束的强度乘以此值。默认值为 10。
</td></tr>
</tbody>
</table>

碎块上会写入属性 <code>cluster</code>。

#### RBD Exploded View
把碎块从中心向外推开，用于检查破碎结果。对应 H-Style 的 Exploded View。

<p align="center">
  <img width="35%" src="Docs/Images/Nodes/exploded_view.png" alt="RBD Exploded View"><br>
  <font color="grey">RBD Exploded View</font>
</p>

本节点只连接 **Geometry**。检查完成后请删除或屏蔽（选中后按 `M`）。

<table width="100%">
<thead>
<tr><td colspan="3"><b>输入</b></td><td><b>说明</b></td></tr>
</thead>
<tbody>
<tr><td colspan="3"><b>Scale</b></td><td>
缩放。碎块被推开的距离。
</td></tr>
</tbody>
</table>

要查看约束，请在节点编辑器中对任意 RBD 节点的 **Constraint Geometry** 输出按 `Ctrl+Shift+左键`，将其连接到查看器节点。

#### RBD Bullet Solver
解算刚体。对应 H-Style 的同名节点。

解算由侧栏的 **Bake** 按钮执行，详情请参阅[烘焙](#烘焙)。

<p align="center">
  <img width="35%" src="Docs/Images/Nodes/bullet_solver.png" alt="RBD Bullet Solver"><br>
  <font color="grey">RBD Bullet Solver</font>
</p>

本节点的设置由烘焙按钮读取，因此必须直接在节点上指定，不能由其他节点的连线提供（三路数据的输入除外）。

<table width="100%">
<thead>
<tr><td colspan="3"><b>输入</b></td><td><b>说明</b></td></tr>
</thead>
<tbody>
<tr><td colspan="3"><b>Start Frame</b> / <b>End Frame</b></td><td>
起始帧、结束帧。解算的帧范围。
</td></tr>
<tr><td colspan="3"><b>Time Scale</b></td><td>
时间比例。烘焙结果的回放速度。0.5 为慢动作。
</td></tr>
<tr><td colspan="3"><b>Simulation</b></td><td>
模拟。参数组。
</td></tr>
<tr><td></td><td colspan="2"><b>Bullet Substeps</b></td><td>
Bullet 子步数。每帧的解算步数。碎块运动很快或很薄时请增大。
</td></tr>
<tr><td></td><td colspan="2"><b>Constraint Iterations</b></td><td>
约束迭代。每一步中求解碰撞和约束的迭代次数。
</td></tr>
<tr><td></td><td colspan="2"><b>Glue Iterations</b></td><td>
胶合迭代。用于每条胶合的迭代次数。数值越大，粘在一起的碎块越硬，解算也越慢。设置为 0 时与约束迭代相同。
</td></tr>
<tr><td colspan="3"><b>Properties</b></td><td>
属性。参数组。
</td></tr>
<tr><td></td><td colspan="2"><b>Density</b> / <b>Bounce</b> / <b>Friction</b></td><td>
密度、回弹、摩擦。未由 <a href="#rbd-configure">RBD Configure</a> 设置的碎块使用这里的值。密度的单位为千克/立方米。
</td></tr>
<tr><td></td><td colspan="2"><b>Collision Padding</b></td><td>
碰撞间隙。碰撞体外侧的间隙。
</td></tr>
<tr><td></td><td colspan="2"><b>Linear Damping</b> / <b>Angular Damping</b></td><td>
线性阻尼、角度阻尼。移动和旋转的衰减。
</td></tr>
<tr><td></td><td colspan="2"><b>Start Asleep</b></td><td>
初始休眠。启用时，碎块保持不动，直到被碰撞。
</td></tr>
<tr><td colspan="3"><b>Collision</b></td><td>
碰撞。参数组。
</td></tr>
<tr><td></td><td colspan="2"><b>Collision Objects</b></td><td>
碰撞物体。与碎块碰撞的物体所在的集合。这些物体按各自的动画运动。
</td></tr>
<tr><td></td><td colspan="2"><b>Ground Plane</b> / <b>Ground Height</b></td><td>
地面、地面高度。启用地面，以及地面在世界空间中的高度。
</td></tr>
<tr><td colspan="3"><b>Forces</b></td><td>
力场。参数组。
</td></tr>
<tr><td></td><td colspan="2"><b>Gravity</b></td><td>
重力。重力加速度。
</td></tr>
<tr><td></td><td colspan="2"><b>Force Fields</b></td><td>
力场。启用时，场景中的 Blender 力场作用于碎块（默认）。详情请参阅<a href="#初速度与力场">初速度与力场</a>。
</td></tr>
<tr><td></td><td colspan="2"><b>Field Weight</b></td><td>
力场权重。所有力场的强度乘以此值。不影响重力。
</td></tr>
<tr><td></td><td colspan="2"><b>Limit To</b></td><td>
限定集合。指定后，只有该集合中的力场起作用。留空时使用场景中所有的力场。
</td></tr>
<tr><td colspan="3"><b>Cache</b></td><td>
缓存。参数组，默认折叠。其中的内容由烘焙按钮填写，通常不需要手动修改。
</td></tr>
<tr><td></td><td colspan="2"><b>Frame Offset</b></td><td>
帧偏移。把烘焙的运动在时间上平移，单位为帧。
</td></tr>
</tbody>
</table>

## 属性
RBD 节点之间通过以下属性传递数据。在节点之间插入自己的节点读写这些属性，即可实现节点本身没有提供的控制。

碎块上的属性位于点域，解算时按碎块取平均值。

<table width="100%">
<thead>
<tr><td><b>属性</b></td><td><b>类型</b></td><td><b>写入的节点</b></td><td><b>说明</b></td></tr>
</thead>
<tbody>
<tr><td colspan="4"><b>Geometry</b></td></tr>
<tr><td><code>piece_id</code></td><td>整数 / 点</td><td>Material Fracture、Assemble</td><td>顶点所属的碎块。相当于 H-Style 的 <code>name</code></td></tr>
<tr><td><code>inside</code></td><td>布尔 / 面</td><td>Material Fracture、Assemble</td><td>是否为切割产生的内表面。相当于 H-Style 的 <code>inside</code> 组</td></tr>
<tr><td><code>rbd_pivot</code></td><td>矢量 / 点</td><td>Material Fracture、Assemble</td><td>碎块的中心</td></tr>
<tr><td><code>rbd_rest</code></td><td>矢量 / 点</td><td>Material Fracture、Assemble</td><td>加上切面凹凸之前的位置</td></tr>
<tr><td><code>active</code></td><td>布尔 / 点</td><td>Configure</td><td>为假时不参与解算，只作为障碍物</td></tr>
<tr><td><code>v</code>、<code>w</code></td><td>矢量 / 点</td><td>Configure</td><td>交给解算器时的速度和角速度</td></tr>
<tr><td><code>activate_time</code></td><td>浮点 / 点</td><td>Configure</td><td>起始帧之后多少秒交给解算器</td></tr>
<tr><td><code>density</code>、<code>friction</code>、<code>bounce</code></td><td>浮点 / 点</td><td>Configure</td><td>负值表示未设置，使用解算节点上的值</td></tr>
<tr><td><code>cluster</code></td><td>整数 / 点</td><td>Cluster</td><td>簇的编号</td></tr>
<tr><td colspan="4"><b>Constraint Geometry</b></td></tr>
<tr><td><code>piece_id</code></td><td>整数 / 点</td><td>Material Fracture、Constraints From Rules</td><td>边的这一端连接的碎块</td></tr>
<tr><td><code>strength</code></td><td>浮点 / 边</td><td>Material Fracture、Constraints From Rules、Constraint Properties、Cluster</td><td>胶合断开的阈值</td></tr>
<tr><td><code>area</code></td><td>浮点 / 边</td><td>Material Fracture、Constraints From Rules</td><td>接触面积</td></tr>
<tr><td><code>anchor</code></td><td>矢量 / 边</td><td>Material Fracture、Constraints From Rules</td><td>两块碎块接触的位置</td></tr>
</tbody>
</table>

## 初速度与力场
让碎块运动的方式有两种，可以单独使用，也可以同时使用。

<table width="100%">
<thead>
<tr><td></td><td><b>初速度</b></td><td><b>力场</b></td></tr>
</thead>
<tbody>
<tr><td><b>设置位置</b></td><td><code>RBD Configure</code> 的 <b>Set Initial Velocity</b></td><td>在场景中添加 Blender 的力场物体（<code>Shift+A</code> > Force Field），并启用 <code>RBD Bullet Solver</code> 的 <b>Force Fields</b></td></tr>
<tr><td><b>作用方式</b></td><td>碎块交给解算器的瞬间获得一次速度</td><td>在整段解算中持续作用</td></tr>
<tr><td><b>适用场合</b></td><td>爆炸、冲击等瞬间的效果</td><td>风、湍流、涡流、阻力等持续的效果</td></tr>
</tbody>
</table>

<p align="center">
  <img width="80%" src="Docs/Images/node_example_wind.png" alt="Initial velocity and force fields"><br>
  <font color="grey">同时启用初速度和力场的网络（示例 07）</font>
</p>

力场的作用方式与 Blender 自带的刚体相同。

* 力场物体可以设置动画
* 强度为 `S` 的力场对每块碎块施加 `S ÷ 帧率` 牛顿的力，因此 `加速度 = 强度 × Field Weight ÷ (帧率 × 碎块质量)`
* 例如，要使一块 3 千克的碎块在 24 帧/秒下获得 10 米/秒² 的加速度，需要约 720 的强度
* 较轻的碎块加速较快
* 力作用于碎块的质心，本身不使碎块旋转
* 尚未激活的碎块和 **Active** 被禁用的碎块不受力场影响
* 启用了 **Start Asleep** 的碎块受到力场作用时会立即醒来
* 带有初速度的碎块，力场晚一帧开始作用

## 多个物体一起解算
每个物体拥有各自的 RBD 网络。

选中多个带有 `RBD Bullet Solver` 的物体后，烘焙按钮变为 **Bake N Objects Together**（一起烘焙 N 个物体）。  
这些物体在同一个世界中解算，碎块之间相互碰撞；结果分别保存在各自的节点上，导出也分别进行。

* 写在属性中的内容（初速度、是否参与解算、激活时间、约束）各物体独立
* `RBD Bullet Solver` 上的参数使用活动物体的节点上的值
* 不同物体的碎块之间没有约束
* 全部烘焙成功，或者全部不变

## 导出
烘焙之后，可以使用侧栏底部的三个导出按钮。

<table width="100%">
<thead>
<tr><td><b>按钮</b></td><td><b>导出内容</b></td><td><b>用途</b></td></tr>
</thead>
<tbody>
<tr><td><b>Export FBX (Bones)</b></td><td>导出 FBX（骨骼）。每块碎块一根骨骼的蒙皮网格和烘焙动画</td><td>在 Unity 或 Unreal 中作为普通的骨骼动画使用</td></tr>
<tr><td><b>Export VAT</b></td><td>导出 VAT。网格 <code>.fbx</code>、位置贴图和旋转贴图 <code>.exr</code> 和 <code>.json</code></td><td>大量实例、在 GPU 上播放</td></tr>
<tr><td><b>Export Alembic</b></td><td>导出 Alembic。逐帧的动画网格 <code>.abc</code></td><td>其他 DCC、离线渲染</td></tr>
</tbody>
</table>

FBX 和 VAT 导出的是原始的烘焙结果，不受 **Time Scale** 和 **Frame Offset** 影响。Alembic 导出的是视口中显示的结果。

FBX 和 VAT 的导出选项如下。

<table width="100%">
<thead>
<tr><td colspan="3"><b>选项</b></td><td><b>说明</b></td></tr>
</thead>
<tbody>
<tr><td colspan="3"><b>Merge Unbroken Pieces</b></td><td>
合并没分开的碎块。启用时（默认），整段动画中始终没有分开的相邻碎块合并为一块，始终不动的碎块也合并为一块，夹在它们之间的切面被删除。<br>
骨骼数（或 VAT 贴图的列数）和面数减少，画面不变。
</td></tr>
<tr><td></td><td colspan="2"><b>Merge Tolerance</b></td><td>
合并容差。合并后，碎块上任意一点偏离解算结果的距离不超过此值时才合并。默认值为 1 厘米。
</td></tr>
<tr><td colspan="3"><b>Target</b></td><td>
目标。
<p>
<b>仅 VAT。</b>
</p>
<p>
<ul>
<li>Unity: 数据换算为 Unity 的轴向（默认）</li>
<li>Blender Axes（Blender 轴向）: 数据保持 Blender 的轴向</li>
</ul>
</p>
</td></tr>
<tr><td colspan="3"><b>Keep Rig in Scene</b></td><td>
把骨架留在场景里。<b>仅 FBX。</b>导出后保留生成的骨架和蒙皮网格。
</td></tr>
</tbody>
</table>

#### 在 Unity 中使用

**骨骼 FBX**  
把文件放入工程，在模型的 Import Settings 中把 **Animation > Anim. Compression** 设置为 **Off**。  
也可以选中 `.fbx` 后执行菜单 **Assets > H-Style RBD Nodes > Fix Bone FBX Import**。  
默认的 Keyframe Reduction 会使快速翻滚的碎块产生 1 到 2 厘米的偏差。

**VAT**  
先把下表中 Unity 用的四个文件放入工程，位置不限，只要在 `Assets` 下。  
再把导出的文件放入 `Assets` 下的一个文件夹，选中导出的 `.json`，执行菜单 **Assets > H-Style RBD Nodes > Set Up VAT From Json**。  
贴图的导入设置、材质和预制体会自动生成，预制体可以直接放入场景。

Unity 用的文件不包含在扩展中，需要另行下载：本仓库的 [`Unity`](Unity) 文件夹，或 [Releases](https://github.com/excifroge/H-Style-RBD-Nodes/releases) 页面上的 `h_style_rbd_unity-x.y.z.zip`。  
一个 Unity 工程中只需要保留一份。

<table width="100%">
<thead>
<tr><td><b>文件</b></td><td><b>说明</b></td></tr>
</thead>
<tbody>
<tr><td><code>HStyleRbdVAT_URP.shader</code></td><td>可直接使用的 URP 着色器，包含阴影和深度通道。光照只计算主方向光和环境光</td></tr>
<tr><td><code>HStyleRbdVAT.hlsl</code></td><td>解码函数。接入自己的着色器时调用，用法写在文件开头</td></tr>
<tr><td><code>HStyleRbdVatSetup.cs</code></td><td>上述的设置菜单（编辑器脚本）</td></tr>
<tr><td><code>HStyleRbdVatPlayer.cs</code></td><td>播放组件（运行时脚本）</td></tr>
</tbody>
</table>

预制体上的播放组件 `HStyleRbdVatPlayer` 用于控制一次性的播放。

<table width="100%">
<thead>
<tr><td><b>属性名</b></td><td><b>说明</b></td></tr>
</thead>
<tbody>
<tr><td><b>Play On Enable</b></td><td>物体激活时自动从头播放</td></tr>
<tr><td><b>Loop</b> / <b>Hold At End</b></td><td>循环播放；每一轮在最后一帧停留的秒数</td></tr>
<tr><td><b>Speed</b></td><td>播放速度</td></tr>
<tr><td><b>Break Particles</b></td><td>可选。指定一个 Particle System 后，每条裂缝张开的瞬间在裂缝的位置发射粒子</td></tr>
<tr><td><b>Particles Per Metre</b> / <b>Max Particles Per Crack</b> / <b>Min Crack Size</b></td><td>裂缝越大发射越多；每条裂缝的上限；小于此尺寸的裂缝不发射</td></tr>
</tbody>
</table>

用于 **Break Particles** 的 Particle System，请把 Emission 的发射率设置为 0，并禁用 Play On Awake。  
从脚本控制时使用 `Play()`、`Seek(秒)`，或在 `Stop()` 之后自行调用 `Advance(dt)`。

FBX 和 VAT 的网格带有一组顶点色，可在着色器中用于逐块的效果。数值是线性的，精度为 8 位。

<table width="100%">
<thead>
<tr><td><b>通道</b></td><td><b>内容</b></td></tr>
</thead>
<tbody>
<tr><td>R</td><td>每块碎块的随机数</td></tr>
<tr><td>G</td><td>碎块开始运动的时刻。0 为第一帧，1 为最后一帧或始终未动</td></tr>
<tr><td>B</td><td>碎块到冲击点的距离。0 为最近，1 为最远</td></tr>
<tr><td>A</td><td>内表面为 1，原表面为 0</td></tr>
</tbody>
</table>

VAT 的 `.json` 中还记录了断裂事件：每一对相邻碎块分开的时刻、位置、裂缝的大小和张开的速度（`event_times`、`event_positions`、`event_sizes`、`event_speeds`）。  
播放组件使用这份数据发射粒子，也可以直接读取后用于 VFX Graph、音效或镜头震动。

#### VAT 格式
本扩展使用自己的格式 `hrbd_vat_1`，与其他工具的 VAT 着色器不兼容。

* 贴图的宽度为不小于（碎块数 + 1）的最小的 2 的幂，高度为不小于（帧数 + 1）的最小的 2 的幂
* 第 `k` 行为烘焙的第 `k` 帧，`pivot_row` 所指的行保存每块碎块的静止轴心
* 位置贴图的 RGB 为该帧碎块轴心的位置，旋转贴图的 RGBA 为相对静止姿态的四元数 xyzw
* 坐标位于导出网格的物体空间，已换算为目标引擎的轴向（Unity：Blender 的 `(x, y, z)` 变为 `(-x, z, -y)`）
* 网格的第二个 UV 通道 (`TEXCOORD1`) 的 u 为 `(碎块编号 + 0.5) / 贴图宽度`
* 解码：`位置 = 该帧的轴心 + 旋转(顶点 - 静止轴心)`，法线和切线只进行旋转
* 贴图使用 RGBA Half 时，10 米范围内的误差约为 2 到 3 毫米

手动设置贴图时，请在 Import Settings 中禁用 sRGB 和 Generate Mip Maps，并把 Filter Mode 设置为 Point、Wrap Mode 设置为 Clamp、Compression 设置为 None、Non-Power of 2 设置为 None。

## 示例
`Examples` 文件夹中有 7 个已经烘焙好的示例。打开后选中破碎的物体，在几何节点编辑器中即可查看其 RBD 网络。

<table width="100%">
<thead>
<tr><td><b>文件</b></td><td><b>内容</b></td><td><b>节点</b></td></tr>
</thead>
<tbody>
<tr><td><code>01_wall_smash</code></td><td>被球撞穿的墙</td><td>Material Fracture → Cluster → Configure（+ Select）→ Bullet Solver</td></tr>
<tr><td><code>02_ground_crack</code></td><td>地裂</td><td>Material Fracture（Cut Through）→ Configure（Set Initial Velocity + Set Activation）→ Bullet Solver</td></tr>
<tr><td><code>03_explosion</code></td><td>爆炸</td><td>Material Fracture → Configure（Set Initial Velocity）→ Bullet Solver</td></tr>
<tr><td><code>04_glass</code></td><td>被击穿的玻璃</td><td>Material Fracture（Glass）→ Configure（+ Select）→ Bullet Solver</td></tr>
<tr><td><code>05_wood_post</code></td><td>被撞断的木柱</td><td>Material Fracture（Wood）→ Cluster → Configure（+ Select）→ Bullet Solver</td></tr>
<tr><td><code>06_brick_wall</code></td><td>由现成的砖块组成的墙</td><td>Assemble → Constraints From Rules → Configure（+ 两个 Select）→ Bullet Solver</td></tr>
<tr><td><code>07_explosion_wind</code></td><td>风中的爆炸</td><td>Material Fracture → Configure（Set Initial Velocity）→ Bullet Solver，以及风和湍流两个力场</td></tr>
</tbody>
</table>

<p align="center">
  <img width="80%" src="Docs/Images/node_example_wall.png" alt="01_wall_smash"><br>
  <font color="grey">01_wall_smash 的 RBD 网络</font>
</p>

<p align="center">
  <img width="80%" src="Docs/Images/node_example_bricks.png" alt="06_brick_wall"><br>
  <font color="grey">06_brick_wall 的 RBD 网络。两个 RBD Select 通过布尔运算节点组合</font>
</p>

这些示例由 `Examples/make_examples.py` 生成。

## 限制
* 只在 Blender 5.2 上核对过
* Unity 侧只在 Unity 6000.0 和 URP 17 上核对过；Unreal 未经核对
* `RBD Bullet Solver` 本身不进行解算，修改上游的参数后需要重新烘焙
* 要破碎的模型应为封闭的网格。有洞、未焊接或单层的面片会产生不封闭的碎块，侧栏中会显示警告
* 碎块使用凸包作为碰撞体，凹形的碎块会被填平
* 胶合有弹性：受到冲击时，未断开的位置也可能张开细缝后再合上。增大 **Glue Iterations** 可以减轻
* 胶合的断开各自独立判断，没有冲击沿约束网络传播和衰减的过程
* 形状随时间变化的碰撞物体（骨骼蒙皮、形态键）产生的冲击偏大
* 已烘焙的物体不能可靠地作为另一次烘焙的碰撞物体，请改为[多个物体一起解算](#多个物体一起解算)
* 力场的强度换算与 Blender 的刚体相同，数值需要远大于常用的范围；实际测试过的力场类型只有风和力
* 位置类的参数在物体自身空间中指定，只有地面高度在世界空间中指定
* 玻璃的裂纹是近似的：环形裂纹是分段的折线，没有从主裂纹上分叉的细裂纹
* 二级破碎是近似的，没有崩角 (Chipping)，也没有解算过程中的再次破碎
* `RBD Constraints From Rules` 的接触面积是估算值；很小的接触面可能无法识别
* 启用 **Detail** 后，切面与外表面在接缝处位置重合但没有焊接
* 每块碎块在解算时对应一个 Blender 物体。500 块没有问题，2000 块以上会明显变慢
* 断裂事件只随 VAT 导出
* 场景的单位缩放不为 1 时不予考虑，一个 Blender 单位始终视为 1 米
* 导出会直接覆盖同名的文件

实测数据、实现方式和测试方法请参阅 [AGENTS.md](AGENTS.md)（英文）。

## 商标
Blender 是 Blender Foundation 的商标。Unity 是 Unity Technologies 的商标。

## 许可证
本扩展以 GPL-3.0-or-later 许可证发布。

[`Unity`](Unity) 文件夹中的 `HStyleRbdVAT.hlsl`、`HStyleRbdVAT_URP.shader`、`HStyleRbdVatSetup.cs`、`HStyleRbdVatPlayer.cs` 以 CC0-1.0 发布，可以直接复制到任何工程中使用。
