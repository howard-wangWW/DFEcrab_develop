"""
PDF 读取能力测试

测试流程：codebuddy 开发 -> dfecrab 自测
"""

import asyncio
import sys
import os
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


async def test_pdf_service():
    """测试 PDF 服务"""
    print("\n" + "=" * 60)
    print("📄 PDF 服务测试")
    print("=" * 60)

    from src.services.pdf_service import get_pdf_service

    service = get_pdf_service()
    await service.initialize()

    print("\n✅ PDF 服务初始化成功")

    # 测试 1: 查找测试 PDF 文件
    test_pdf = None
    pdf_dirs = [
        Path(project_root) / "docs",
        Path(project_root) / "tests" / "fixtures",
        Path.home() / "Downloads",
    ]

    # 创建一个简单的测试 PDF
    test_pdf_path = Path(project_root) / "tests" / "test_sample.pdf"
    test_pdf_path.parent.mkdir(parents=True, exist_ok=True)

    # 使用 PyMuPDF 创建测试 PDF
    try:
        import fitz
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50, 50), "Hello, PDF Service!")
        page.insert_text((50, 100), "This is a test document for DFEcrab.")
        page.insert_text((50, 150), "Testing PDF reading capabilities.")
        doc.save(str(test_pdf_path))
        doc.close()
        test_pdf = test_pdf_path
        print(f"\n📝 创建测试 PDF: {test_pdf}")
    except ImportError:
        print("\n⚠️  PyMuPDF 未安装，跳过 PDF 创建")

    if not test_pdf or not test_pdf.exists():
        print("\n⚠️  没有可用的测试 PDF 文件")
        return False

    # 测试 2: 提取文本
    print("\n📋 测试 1: 提取文本")
    try:
        result = service.extract_text(str(test_pdf))
        print(f"   总页数: {result['total_pages']}")
        print(f"   提取页数: {result['extracted_pages']}")
        print(f"   文本长度: {len(result['text'])} 字符")
        print(f"   文本预览: {result['text'][:100]}...")
        print("   ✅ 文本提取成功")
    except Exception as e:
        print(f"   ❌ 文本提取失败: {e}")
        return False

    # 测试 3: 提取指定页
    print("\n📋 测试 2: 提取指定页")
    try:
        result = service.extract_text(str(test_pdf), pages=[1])
        print(f"   提取页数: {result['extracted_pages']}")
        print("   ✅ 指定页提取成功")
    except Exception as e:
        print(f"   ❌ 指定页提取失败: {e}")
        return False

    # 测试 4: 获取元数据
    print("\n📋 测试 3: 获取元数据")
    try:
        metadata = service.get_metadata(str(test_pdf))
        print(f"   总页数: {metadata['total_pages']}")
        print(f"   页面尺寸: {metadata['page_size']}")
        print("   ✅ 元数据获取成功")
    except Exception as e:
        print(f"   ❌ 元数据获取失败: {e}")
        return False

    # 测试 5: 表格识别
    print("\n📋 测试 4: 表格识别")
    try:
        tables = service.extract_tables(str(test_pdf))
        print(f"   检测到 {len(tables)} 个表格")
        print("   ✅ 表格识别成功")
    except Exception as e:
        print(f"   ⚠️  表格识别: {e}")

    # 测试 6: 综合分析
    print("\n📋 测试 5: 综合分析")
    try:
        analysis = service.analyze(str(test_pdf))
        print(f"   元数据: {analysis['metadata']['total_pages']} 页")
        print(f"   表格数: {len(analysis['tables'])}")
        print(f"   书签数: {len(analysis['bookmarks'])}")
        print("   ✅ 综合分析成功")
    except Exception as e:
        print(f"   ❌ 综合分析失败: {e}")
        return False

    # 清理测试文件
    if test_pdf.exists():
        test_pdf.unlink()

    print("\n" + "=" * 60)
    print("✅ PDF 服务测试通过")
    print("=" * 60)

    return True


async def test_pdf_reader_skill():
    """测试 PDF Reader Skill"""
    print("\n" + "=" * 60)
    print("🔧 PDF Reader Skill 测试")
    print("=" * 60)

    # 动态导入 skill
    skill_path = Path(project_root) / "skills" / "pdf-reader" / "execute.py"
    import importlib.util
    spec = importlib.util.spec_from_file_location("pdf_reader_execute", skill_path)
    pdf_reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pdf_reader)
    execute = pdf_reader.execute

    # 创建测试 PDF
    try:
        import fitz
        test_pdf = Path(project_root) / "tests" / "test_skill.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50, 50), "Skill Test: PDF Reader")
        page.insert_text((50, 100), "Testing skill execution.")
        doc.save(str(test_pdf))
        doc.close()
        pdf_created = True
    except ImportError:
        print("   ⚠️  PyMuPDF 未安装，跳过 Skill 测试")
        return True  # 跳过但不算失败

    if not pdf_created:
        return True

    # 测试 Skill
    result = execute(file_path=str(test_pdf))

    print(f"\n   状态: {result['status']}")
    if result['status'] == 'SUCCESS':
        content = result['content']
        print(f"   总页数: {content['total_pages']}")
        print(f"   文本预览: {content['text'][:50]}...")
        print("   ✅ Skill 执行成功")
    else:
        print(f"   错误: {result['content'].get('error')}")
        print("   ❌ Skill 执行失败")

    # 清理
    if 'test_pdf' in locals() and test_pdf.exists():
        test_pdf.unlink()

    return result['status'] == 'SUCCESS'


async def main():
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("🚀 DFEcrab PDF 读取能力 - 自测")
    print("=" * 60)

    results = []

    # 测试 PDF 服务
    results.append(("PDF 服务", await test_pdf_service()))

    # 测试 Skill
    results.append(("PDF Reader Skill", await test_pdf_reader_skill()))

    # 汇总
    print("\n" + "=" * 60)
    print("📊 测试汇总")
    print("=" * 60)

    passed = sum(1 for _, r in results if r)
    for name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"   {name}: {status}")

    print(f"\n   总计: {passed}/{len(results)} 通过")
    print("=" * 60)

    return passed == len(results)


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
