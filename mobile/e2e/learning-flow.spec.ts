import { expect, test } from '@playwright/test'

test('activates, interrupts, resumes, retries the same rating, and completes', async ({ page }) => {
  const activationCode = process.env.WXZY_E2E_ACTIVATION_CODE
  if (!activationCode) throw new Error('WXZY_E2E_ACTIVATION_CODE is required')

  const submittedBodies: string[] = []
  await page.route('**/api/v1/review-attempts', async (route) => {
    submittedBodies.push(route.request().postData() ?? '')
    if (submittedBodies.length === 1) {
      await route.abort('failed')
      return
    }
    await route.continue()
  })

  await page.goto('/#/activate')
  await page.getByLabel('一次性激活码').fill(activationCode)
  await page.getByRole('button', { name: '激活并进入今日学习' }).click()
  await expect(page.getByRole('heading', { name: '今日学习' })).toBeVisible()

  await page.getByRole('link', { name: '学科' }).click()
  await page.getByRole('link', { name: /移动端端到端测试/ }).click()
  await expect(page.getByRole('heading', { name: '阴阳学说' })).toBeVisible()
  await page.getByRole('link', { name: /阴阳的基本关系有哪些/ }).click()
  await expect(page.getByText('阴阳双方相互对立、相互依存')).toBeVisible()

  await page.goto('/#/insights')
  await expect(page.getByText('内容与掌握')).toBeVisible()
  await page.goto('/#/me')
  await expect(page.getByText('Xiaomi 17 Pro · 当前设备')).toBeVisible()
  await page.getByRole('link', { name: '编辑档案' }).click()
  await expect(page.getByLabel('每日分钟')).toHaveValue('20')
  await page.goto('/#/today')

  await page.getByRole('button', { name: '10' }).click()
  await expect(page.getByText('10 分钟')).toBeVisible()
  await page.getByRole('button', { name: '开始今日学习' }).click()
  await expect(page.getByRole('heading', { name: '阴阳的基本关系有哪些？' })).toBeVisible()

  await page.getByRole('button', { name: '保存并退出' }).click()
  await expect(page.getByRole('heading', { name: '今日学习' })).toBeVisible()
  await page.getByRole('button', { name: '开始今日学习' }).click()
  await expect(page.getByRole('heading', { name: '学习已暂停' })).toBeVisible()
  await page.getByRole('button', { name: '继续学习' }).click()

  await page.getByRole('button', { name: '书写强化' }).click()
  await page.getByLabel('写下回忆内容').fill('对立制约，互根互用')
  await page.getByRole('button', { name: '查看答案' }).click()
  await page.getByRole('checkbox', { name: '对立制约' }).check()
  await page.getByRole('button', { name: '3 良好' }).click()
  await expect(page.getByRole('alert')).toContainText('无法连接服务器')
  await page.getByRole('button', { name: '原样重试' }).click()

  await expect(page.getByRole('heading', { name: '今日学习完成' })).toBeVisible()
  expect(submittedBodies).toHaveLength(2)
  expect(JSON.parse(submittedBodies[1])).toEqual(JSON.parse(submittedBodies[0]))
})
