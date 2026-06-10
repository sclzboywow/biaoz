// 数据读写脚本
// 功能：支持单条/批量写入、分页读取、列出数据表
// 版本：2.1
// 更新时间：2026-06-10
// v2.1 变更：read 支持 offset 分页，返回 next offset，全量拉取必备

// 1. 获取当前表格
let sheet = Application.Selection.GetActiveSheet();
console.log("当前表格:", JSON.stringify(sheet));

// 2. 根据操作类型处理
if (Context.argv.action === "read") {
    try {
        // 构造查询参数
        let sortField = Context.argv.sort_field || "编号";
        let sortOrder = Context.argv.sort_order || "ASC";

        let query = {
            SheetId: sheet.sheetId,
            PageSize: Context.argv.limit || 10,
            Sort: [{
                Field: sortField,
                Order: sortOrder,
            }],
        };

        // 分页游标（全量拉取时由外部传入上一页返回的 offset）
        if (Context.argv.offset) {
            query.Offset = Context.argv.offset;
        }

        // 等值过滤：filter: { "实施状态": "现行" }
        if (Context.argv.filter && Object.keys(Context.argv.filter).length > 0) {
            let filter = {};
            for (let key in Context.argv.filter) {
                filter[key] = {
                    type: "equal",
                    value: Context.argv.filter[key],
                };
            }
            query.Filter = filter;
        }

        console.log("查询参数:", JSON.stringify(query));
        let result = Application.Record.GetRecords(query);
        console.log(
            "查询结果条数:",
            (result.records || []).length,
            "offset:",
            result.offset || null
        );

        return JSON.stringify({
            success: true,
            records: result.records || [],
            offset: result.offset || null,
            count: (result.records || []).length,
        });
    } catch (e) {
        console.log("查询出错:", e.message);
        return JSON.stringify({
            success: false,
            error: e.message,
        });
    }
} else if (Context.argv.action === "write") {
    try {
        // 支持单条和批量写入
        let records;

        if (Array.isArray(Context.argv.data)) {
            records = Context.argv.data.map(function (item) {
                return { fields: item };
            });
            console.log("准备批量写入 " + records.length + " 条记录");
        } else {
            records = [{ fields: Context.argv.data }];
            console.log("准备单条写入");
        }

        let newRecords = Application.Record.CreateRecords({
            SheetId: sheet.sheetId,
            Records: records,
        });

        console.log("写入完成，结果:", JSON.stringify(newRecords));

        return JSON.stringify({
            success: true,
            records: newRecords,
            count: records.length,
        });
    } catch (e) {
        console.log("写入出错:", e.message);
        return JSON.stringify({
            success: false,
            error: e.message,
        });
    }
} else if (Context.argv.action === "list_sheets") {
    try {
        let sheets = Application.Sheets;
        return JSON.stringify({
            success: true,
            sheets: sheets,
        });
    } catch (e) {
        console.log("获取表格列表出错:", e.message);
        return JSON.stringify({
            success: false,
            error: e.message,
        });
    }
} else {
    return JSON.stringify({
        success: false,
        error: "未知的操作类型",
    });
}
