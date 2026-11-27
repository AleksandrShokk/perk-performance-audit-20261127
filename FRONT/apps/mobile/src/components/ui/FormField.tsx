import {
  type Control,
  Controller,
  type FieldValues,
  type Path
} from 'react-hook-form'

import { TextField, type TextFieldProps } from './TextField'

type FormFieldProps<Values extends FieldValues> = Omit<
  TextFieldProps,
  'value' | 'onChangeText' | 'error'
> & {
  control: Control<Values>
  name: Path<Values>
}

/** Поле, подключённое к React Hook Form: значение, проверка и ошибка из схемы. */
export function FormField<Values extends FieldValues>({
  control,
  name,
  ...props
}: FormFieldProps<Values>) {
  return (
    <Controller
      control={control}
      name={name}
      render={({ field, fieldState }) => (
        <TextField
          {...props}
          ref={field.ref}
          value={field.value ?? ''}
          onChangeText={field.onChange}
          onBlur={field.onBlur}
          error={fieldState.error?.message}
        />
      )}
    />
  )
}
