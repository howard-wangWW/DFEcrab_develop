# 昆明配网查询分类

## 分类规则
- **跳闸相关**：
  - **12=某局跳闸**：含"XX局跳闸/XX供电局"（如"西山局今天有跳闸"）。参数：category=12, bureau。默认当天0点到当前时间，如需指定时间则提取startTime, endTime
  - **11=保供电跳闸**：含"保供电"。参数：category=11, startTime, endTime
  - **10=城区一小时跳闸**：含"城区一小时/1小时"。参数：category=10, startTime, endTime
  - **6=跳闸统计**：其他跳闸查询。参数：category=6, startTime, endTime
- **13=重过载**：含"重过载/过载"。参数：category=13, mode, area, date, days, load_threshold
  - mode推断：含"XX局"→area_count；"汇总/全局"→total_count；"趋势/最近N天"→trend；"详细/列表"→detail；"最多/排行"→top_feeders；默认→total_count
- **8=受令资格**：含"受令资格/调度受令"。参数：category=8, personName
- **9=异常信号统计**：含"异常信号"。参数：category=9, date
- **7=早会材料**：含"早会材料"。参数：category=7, startTime, endTime
- **5=其他对话**：未命中以上任何业务分类时，返回 category=5。此类问题不需要调用 kunming_api，
  如属理论/规程/操作票类知识问答，请如实告知用户该问题超出昆明配网数据查询范围（由知识库专家承接）。

## 判断原则
如果同时匹配多个类别，选择描述最具体的那个。例如：提到"西山局跳闸"优先选12，而不是6。
如果未命中跳闸、早会、受令资格、异常信号、重过载等现有业务类，不要强行归类，统一返回5（其他对话）。

## 输出要求
返回 JSON 包含：category, startTime, endTime, personName, date, bureau, mode, area, days, load_threshold。时间从文本中提取。
