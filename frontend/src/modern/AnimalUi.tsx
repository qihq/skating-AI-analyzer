import type { ComponentProps, ReactNode } from "react";
import {
  Button as AnimalButton,
  Checkbox,
  Card,
  Collapse,
  Divider,
  Drawer,
  Input,
  Loading,
  Modal,
  Notification,
  Progress,
  Radio,
  Select,
  Switch,
  Table,
  Tabs,
  Tag,
  Title,
  Tooltip,
} from "animal-island-ui";
import "animal-island-ui/style";

type ButtonProps = ComponentProps<typeof AnimalButton> & { children: ReactNode };

export function Button({ htmlType = "button", size = "middle", children, ...props }: ButtonProps) {
  return <AnimalButton htmlType={htmlType} size={size} {...props}>{children}</AnimalButton>;
}

export { Card, Checkbox, Collapse, Divider, Drawer, Input, Loading, Modal, Notification, Progress, Radio, Select, Switch, Table, Tabs, Tag, Title, Tooltip };
