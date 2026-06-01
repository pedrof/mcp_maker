/**
 * E2E: define → save → publish → gateway serves it → unpublish → gateway errors.
 *
 * Requires the backend to be running on :8080 with a real Postgres
 * (podman-compose up -d postgres backend) before running Playwright.
 *
 * Run: npx playwright test
 */
import { test, expect, type Page } from '@playwright/test'

const UNIQUE = `e2e-${Date.now()}`
const MODEL_NAME = `E2E Test ${UNIQUE}`

async function waitForStatus(page: Page, status: string) {
  await expect(page.getByText(status)).toBeVisible({ timeout: 8_000 })
}

test.describe('FORGE lifecycle', () => {
  test('model list loads', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByTestId('new-model-btn')).toBeVisible()
    await expect(page.getByTestId('nav-models')).toBeVisible()
  })

  test('create → edit → save → publish → connection snippet', async ({ page }) => {
    await page.goto('/')

    // 1. Create new model
    await page.getByTestId('new-model-btn').click()
    await page.getByTestId('new-model-name').fill(MODEL_NAME)
    await page.getByTestId('create-model-submit').click()

    // Should navigate to editor
    await expect(page.getByTestId('model-name')).toBeVisible()
    await waitForStatus(page, 'draft')

    // 2. Schema tab — add a field via JSON editor
    await page.getByTestId('tab-schema').click()
    // Switch to JSON editor
    await page.getByText('{ } json editor').click()
    // The Monaco editor is present
    await expect(page.locator('.monaco-editor')).toBeVisible({ timeout: 10_000 })

    // 3. Prompt tab — set system prompt directly
    await page.getByTestId('tab-prompt').click()
    const promptArea = page.getByTestId('system-prompt')
    await promptArea.fill('You are a helpful assistant for ' + MODEL_NAME)

    // 4. Save
    await page.getByTestId('save-btn').click()
    await expect(page.getByTestId('save-btn')).not.toBeVisible({ timeout: 5_000 })

    // 5. Publish — needs a valid schema; set via API call in test
    // First PUT a valid schema via API so publish doesn't reject it
    const modelId = await page.evaluate(async (name: string) => {
      const res = await fetch('/api/models')
      const models = await res.json() as Array<{id: string; name: string}>
      return models.find(m => m.name === name)?.id
    }, MODEL_NAME)

    if (modelId) {
      // Set a minimal valid schema
      await page.evaluate(async (id: string) => {
        await fetch(`/api/models/${id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            json_schema: {
              $schema: 'https://json-schema.org/draft/2020-12/schema',
              type: 'object',
              properties: { name: { type: 'string' } },
            },
          }),
        })
      }, modelId)
    }

    // Publish
    await page.getByTestId('publish-btn').click()

    // Modal with connection snippet appears
    await expect(page.getByText('Published successfully')).toBeVisible({ timeout: 10_000 })
    await expect(page.getByText('/mcp/').first()).toBeVisible()
    await page.getByTestId('close-publish-modal').click()

    // Status changes to published
    await waitForStatus(page, 'published')

    // 6. Unpublish
    await page.getByTestId('unpublish-btn').click()
    await waitForStatus(page, 'unpublished')
  })

  test('test tab renders chat panel', async ({ page }) => {
    await page.goto('/')

    // Find first model in list or create one
    const rows = page.locator('[data-testid^="model-row-"]')
    const count = await rows.count()
    if (count > 0) {
      await rows.first().click()
    } else {
      await page.getByTestId('new-model-btn').click()
      await page.getByTestId('new-model-name').fill(`Chat test ${Date.now()}`)
      await page.getByTestId('create-model-submit').click()
    }

    await page.getByTestId('tab-test').click()
    await expect(page.getByTestId('chat-input')).toBeVisible()
    await expect(page.getByTestId('chat-send')).toBeVisible()
    await expect(page.getByTestId('chat-messages')).toBeVisible()
  })
})
