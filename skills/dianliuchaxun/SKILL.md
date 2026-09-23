---
name: "dianliuchaxun"
description: "查询某一条线的电流值"
always-apply: false
source: "inline"
---

当逐级往下查找环网柜开关，当电流值大于500A，判定这个电流为异常数据，继续往下级找，直到找到正常的电流值
