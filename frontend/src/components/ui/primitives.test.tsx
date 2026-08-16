import { fireEvent, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeAll, describe, expect, it } from "vitest"

import { Badge } from "./badge"
import { Button } from "./button"
import { Card, CardContent, CardHeader, CardTitle } from "./card"
import { Dialog, DialogContent, DialogTitle, DialogTrigger } from "./dialog"
import { Drawer, DrawerContent, DrawerTitle, DrawerTrigger } from "./drawer"
import { Input } from "./input"
import { Label } from "./label"
import { Progress } from "./progress"
import { Slider } from "./slider"
import { Textarea } from "./textarea"

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

beforeAll(() => {
  globalThis.ResizeObserver = ResizeObserverStub
})

describe("RAG-Studio UI primitives", () => {
  it("keeps field names visible and exposes native keyboard and touch-sized controls", async () => {
    const user = userEvent.setup()
    render(
      <form>
        <Label htmlFor="workspace-name">Workspace name</Label>
        <Input id="workspace-name" />
        <Label htmlFor="notes">Notes</Label>
        <Textarea id="notes" />
        <Button type="submit">Save settings</Button>
      </form>,
    )

    const input = screen.getByRole("textbox", { name: "Workspace name" })
    await user.type(input, "Research library")
    expect(input).toHaveValue("Research library")
    expect(screen.getByRole("button", { name: "Save settings" })).toHaveClass("rs-button")
  })

  it("traps focus, closes with Escape, and restores focus to its trigger", async () => {
    const user = userEvent.setup()
    render(
      <Dialog>
        <DialogTrigger asChild>
          <Button>Open preview</Button>
        </DialogTrigger>
        <DialogContent>
          <DialogTitle>Preview source</DialogTitle>
          <Button>Confirm</Button>
        </DialogContent>
      </Dialog>,
    )

    const trigger = screen.getByRole("button", { name: "Open preview" })
    await user.click(trigger)
    expect(screen.getByRole("dialog", { name: "Preview source" })).toBeVisible()
    await user.keyboard("{Escape}")
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })

  it("closes a Drawer with Escape and restores focus to its trigger", async () => {
    const user = userEvent.setup()
    render(
      <Drawer>
        <DrawerTrigger asChild>
          <Button>Open compact navigation</Button>
        </DrawerTrigger>
        <DrawerContent>
          <DrawerTitle>Compact navigation</DrawerTitle>
          <Button>Navigate</Button>
        </DrawerContent>
      </Drawer>,
    )

    const trigger = screen.getByRole("button", { name: "Open compact navigation" })
    await user.click(trigger)
    expect(screen.getByRole("dialog", { name: "Compact navigation" })).toBeVisible()
    await user.keyboard("{Escape}")
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })

  it("provides semantic progress and keyboard-operable slider values", () => {
    const values: number[] = []
    render(
      <>
        <Progress value={32} label="Indexing documents" />
        <Slider
          aria-label="Similarity threshold"
          defaultValue={[40]}
          onValueChange={(value) => values.push(value[0] ?? 0)}
        />
      </>,
    )

    expect(screen.getByRole("progressbar", { name: "Indexing documents" })).toHaveAttribute(
      "aria-valuenow",
      "32",
    )
    const slider = screen.getByRole("slider", { name: "Similarity threshold" })
    fireEvent.keyDown(slider, { key: "ArrowRight" })
    expect(values).toContain(41)
  })

  it("uses semantic status text and composable card regions", () => {
    render(
      <Card>
        <CardHeader>
          <CardTitle>Ingestion status</CardTitle>
          <Badge variant="success">Ready</Badge>
        </CardHeader>
        <CardContent>All documents are available.</CardContent>
      </Card>,
    )

    expect(screen.getByText("Ready")).toHaveAttribute("data-variant", "success")
    expect(screen.getByRole("heading", { name: "Ingestion status" })).toBeVisible()
  })
})
